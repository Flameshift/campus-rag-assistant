package com.aiassistant.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpResponse.BodyHandlers;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import java.util.HexFormat;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;

/**
 * Python AI 服务网关。
 *
 * 前端所有 AI 请求都先进 Spring Boot，再由这里转发到 Python；
 * 这样用户只需要和 Spring Boot 通信，Python 无需单独鉴权。
 */
@Service
public class AiGatewayService {

    // 强制使用 HTTP/1.1：部分 HTTP 服务器对 Java HTTP/2 请求体兼容性不稳定。
    private final HttpClient httpClient = HttpClient.newBuilder()
            .version(HttpClient.Version.HTTP_1_1)
            .build();
    private final String pythonBaseUrl;
    private final byte[] internalAuthSecret;
    private final ObjectMapper objectMapper;

    public AiGatewayService(
            @Value("${ai.python.base-url:http://127.0.0.1:8000}") String pythonBaseUrl,
            @Value("${ai.internal-auth.secret:local-dev-internal-auth-secret}") String internalAuthSecret,
            ObjectMapper objectMapper) {
        this.pythonBaseUrl = pythonBaseUrl.endsWith("/")
                ? pythonBaseUrl.substring(0, pythonBaseUrl.length() - 1)
                : pythonBaseUrl;
        this.internalAuthSecret = internalAuthSecret.getBytes(StandardCharsets.UTF_8);
        this.objectMapper = objectMapper;
    }

    /** 普通 JSON 转发（/api/chat、/api/knowledge/count 等）。 */
    public HttpResponse<String> forwardJson(String pythonPath, String jsonBody, String method) {
        String normalizedMethod = method == null ? "GET" : method.toUpperCase();
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pythonBaseUrl + pythonPath))
                .header("Content-Type", "application/json; charset=utf-8");
        addInternalAuth(builder, normalizedMethod, pythonPath);
        if ("GET".equals(normalizedMethod)) {
            builder.GET();
        } else if ("DELETE".equals(normalizedMethod)) {
            builder.DELETE();
        } else {
            builder.POST(HttpRequest.BodyPublishers.ofString(jsonBody == null ? "" : jsonBody, StandardCharsets.UTF_8));
        }
        return send(builder.build());
    }

    /**
     * 将 Python 的 SSE 字节流逐步复制到 Spring 的响应流。
     *
     * 这是 /api/chat/stream 真正处理流数据的方法，执行四个动作：
     * 1. 构造带内部签名的 POST 请求；
     * 2. 用 InputStream 接收 Python 的 SSE，避免等待完整响应；
     * 3. 每读到一块字节就写浏览器并 flush，同时复制到 captured；
     * 4. 流结束后把 captured 中的 SSE 转成完整答案并返回给 Controller。
     *
     * 返回值不是 SSE payload，而是供 Spring 会话库保存的完整回答文本。
     */
    public String pipePostStream(String pythonPath, String jsonBody, OutputStream sink) throws IOException {
        // [1/4] 构造内部请求。
        // Spring 访问 Python 必须携带 HMAC；Python 会校验时间戳、HTTP 方法和请求路径，
        // 防止绕过 Spring 网关直接调用内部 RAG 接口。
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pythonBaseUrl + pythonPath))
                .header("Content-Type", "application/json; charset=utf-8");
        addInternalAuth(builder, "POST", pythonPath);
        HttpRequest request = builder
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody == null ? "" : jsonBody, StandardCharsets.UTF_8))
                .build();
        try {
            // [2/4] 获取 Python 响应流。
            // 这里必须使用 ofInputStream()；如果改用 ofString()，Java 会等整个答案生成完
            // 才返回，前端也就失去了逐 token 展示能力。
            HttpResponse<InputStream> response = httpClient.send(request, BodyHandlers.ofInputStream());
            if (response.statusCode() >= 400) {
                throw new IOException("Python 服务返回状态码: " + response.statusCode());
            }

            // [3/4] 一边实时转发，一边复制一份完整 SSE 原文。
            // captured 不参与前端响应，只用于流结束后恢复完整回答。
            ByteArrayOutputStream captured = new ByteArrayOutputStream();
            try (InputStream in = response.body()) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    // 先把本次读到的字节写入浏览器输出流。
                    sink.write(buffer, 0, read);

                    // 立即 flush，避免 Tomcat 或 Spring 把多个 token 合并到响应结束时才发送。
                    sink.flush();

                    // 同一块数据再复制到 captured，供流结束后的会话落库使用。
                    captured.write(buffer, 0, read);
                }
            }

            // [4/4] Python 流已结束，将 SSE 事件还原成纯回答文本。
            return extractStreamAnswer(captured.toString(StandardCharsets.UTF_8));
        } catch (InterruptedException ex) {
            // 保留线程中断标记，让上层线程池能够正确感知任务已中断。
            Thread.currentThread().interrupt();
            throw new IOException("转发流式请求被中断", ex);
        }
    }

    /**
     * 从完整 SSE payload 中提取最终回答，供 Spring 会话库保存。
     *
     * 只处理对回答正文有影响的事件：
     * - token：追加增量文本；
     * - replace：用完整复核结果替换此前 token；
     * - error：转换为 IOException，交给控制器和前端降级处理。
     *
     * sources、timings、confidence 等事件不需要进入会话正文。
     */
    private String extractStreamAnswer(String payload) throws IOException {
        StringBuilder answer = new StringBuilder();

        // SSE 以“data: JSON”行传递事件；空行和其他字段不参与答案提取。
        for (String rawLine : payload.split("\\R")) {
            String line = rawLine.trim();
            if (!line.startsWith("data:")) {
                continue;
            }
            String data = line.substring(5).trim();
            if (data.isEmpty()) {
                continue;
            }
            JsonNode event = objectMapper.readTree(data);
            String type = event.path("type").asText("");

            // token 表示增量片段，按到达顺序追加。
            if ("token".equals(type)) {
                answer.append(event.path("content").asText(""));

            // replace 表示 Python 对前文进行整段替换，例如最终复核后覆盖草稿。
            } else if ("replace".equals(type)) {
                answer.setLength(0);
                answer.append(event.path("content").asText(""));

            // error 是业务流中的失败事件，需要让 Controller 感知而不是保存半截回答。
            } else if ("error".equals(type)) {
                throw new IOException(event.path("message").asText("流式生成失败"));
            }
        }
        return answer.toString();
    }

    /** 上传转发：把文件/文本拼成 multipart 后发给 Python。 */
    public HttpResponse<String> forwardUpload(
            String pythonPath,
            MultipartFile file,
            String text,
            String uploadId,
            Long uploadedByUserId,
            String uploaderName) throws IOException {
        String boundary = "----AiGateway" + UUID.randomUUID();
        byte[] body = buildMultipart(
                boundary,
                file,
                text,
                uploadId,
                uploadedByUserId,
                uploaderName);
        String path = pythonPath;
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pythonBaseUrl + path))
                .header("Content-Type", "multipart/form-data; boundary=" + boundary);
        addInternalAuth(builder, "POST", path);
        HttpRequest request = builder
                .POST(HttpRequest.BodyPublishers.ofByteArray(body))
                .build();
        return send(request);
    }

    private HttpResponse<String> send(HttpRequest request) {
        try {
            return httpClient.send(request, BodyHandlers.ofString(StandardCharsets.UTF_8));
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("转发请求被中断", ex);
        } catch (IOException ex) {
            throw new IllegalStateException("无法连接 Python AI 服务: " + ex.getMessage(), ex);
        }
    }

    /**
     * 生成 Spring Boot -> Python 的内部请求签名。
     *
     * 签名内容固定为：时间戳 + 换行 + HTTP 方法 + 换行 + 请求路径。
     * 这样 Python 端可以同时验证请求时效和请求内容，避免把 RAG 服务暴露为公网接口。
     */
    private void addInternalAuth(HttpRequest.Builder builder, String method, String path) {
        // 时间戳用于防止旧请求被重复利用，签名用于证明请求确实来自 Spring Boot。
        String timestamp = String.valueOf(Instant.now().getEpochSecond());
        String payload = timestamp + "\n" + method.toUpperCase() + "\n" + path;
        builder.header("X-Internal-Timestamp", timestamp);
        builder.header("X-Internal-Signature", hmacSha256(payload));
    }

    private String hmacSha256(String payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(internalAuthSecret, "HmacSHA256"));
            return HexFormat.of().formatHex(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("内部服务签名失败", ex);
        }
    }

    private static byte[] buildMultipart(
            String boundary,
            MultipartFile file,
            String text,
            String uploadId,
            Long uploadedByUserId,
            String uploaderName) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        if (uploadId != null) {
            writeTextPart(out, boundary, "upload_id", uploadId);
        }
        if (uploadedByUserId != null) {
            writeTextPart(out, boundary, "uploaded_by_user_id", String.valueOf(uploadedByUserId));
        }
        if (uploaderName != null && !uploaderName.isBlank()) {
            writeTextPart(out, boundary, "uploader_name", uploaderName);
        }
        if (text != null) {
            writeTextPart(out, boundary, "text", text);
        }
        if (file != null && !file.isEmpty()) {
            out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
            out.write(("Content-Disposition: form-data; name=\"file\"; filename=\""
                    + file.getOriginalFilename() + "\"\r\n").getBytes(StandardCharsets.UTF_8));
            out.write("Content-Type: application/octet-stream\r\n\r\n".getBytes(StandardCharsets.UTF_8));
            out.write(file.getBytes());
            out.write("\r\n".getBytes(StandardCharsets.UTF_8));
        }
        out.write(("--" + boundary + "--\r\n").getBytes(StandardCharsets.UTF_8));
        return out.toByteArray();
    }

    private static void writeTextPart(ByteArrayOutputStream out, String boundary, String name, String value)
            throws IOException {
        out.write(("--" + boundary + "\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(("Content-Disposition: form-data; name=\"" + name + "\"\r\n\r\n").getBytes(StandardCharsets.UTF_8));
        out.write(value.getBytes(StandardCharsets.UTF_8));
        out.write("\r\n".getBytes(StandardCharsets.UTF_8));
    }
}
