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

    /** 流式转发：把 Python 的 SSE 字节流原样复制给前端。 */
    public String pipePostStream(String pythonPath, String jsonBody, OutputStream sink) throws IOException {
        HttpRequest.Builder builder = HttpRequest.newBuilder(URI.create(pythonBaseUrl + pythonPath))
                .header("Content-Type", "application/json; charset=utf-8");
        addInternalAuth(builder, "POST", pythonPath);
        HttpRequest request = builder
                .POST(HttpRequest.BodyPublishers.ofString(jsonBody == null ? "" : jsonBody, StandardCharsets.UTF_8))
                .build();
        try {
            HttpResponse<InputStream> response = httpClient.send(request, BodyHandlers.ofInputStream());
            if (response.statusCode() >= 400) {
                throw new IOException("Python 服务返回状态码: " + response.statusCode());
            }
            ByteArrayOutputStream captured = new ByteArrayOutputStream();
            try (InputStream in = response.body()) {
                byte[] buffer = new byte[8192];
                int read;
                while ((read = in.read(buffer)) != -1) {
                    sink.write(buffer, 0, read);
                    // StreamingResponseBody 需要显式 flush，否则 Tomcat 会等响应结束后
                    // 才把 SSE 内容交给浏览器。
                    sink.flush();
                    captured.write(buffer, 0, read);
                }
            }
            return extractStreamAnswer(captured.toString(StandardCharsets.UTF_8));
        } catch (InterruptedException ex) {
            Thread.currentThread().interrupt();
            throw new IOException("转发流式请求被中断", ex);
        }
    }

    private String extractStreamAnswer(String payload) throws IOException {
        StringBuilder answer = new StringBuilder();
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
            if ("token".equals(type)) {
                answer.append(event.path("content").asText(""));
            } else if ("replace".equals(type)) {
                answer.setLength(0);
                answer.append(event.path("content").asText(""));
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

    private void addInternalAuth(HttpRequest.Builder builder, String method, String path) {
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
