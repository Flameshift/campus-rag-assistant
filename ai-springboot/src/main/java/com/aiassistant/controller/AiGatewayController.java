package com.aiassistant.controller;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.aiassistant.security.GuestSessionService;
import com.aiassistant.security.TokenAuthInterceptor;
import com.aiassistant.service.AiGatewayService;
import com.aiassistant.service.ConversationService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Map;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

/**
 * AI 网关：把问答、流式问答、上传转发到 Python 知识库服务。
 *
 * 前端不直接访问 Python，全部请求走这里。
 *
 * /api/chat/stream 的代码调用顺序：
 * Vue sendMessage
 * -> OptionalTokenAuthInterceptor 读取可选登录态
 * -> chatStream() 接收请求
 * -> prepareThreadBody() 生成可信历史和 thread_id
 * -> StreamingResponseBody 异步回调
 * -> AiGatewayService.pipePostStream() 转发 Python SSE
 * -> 浏览器逐块收到 token
 * -> 流结束后为登录用户保存本轮问答
 */
@RestController
public class AiGatewayController {

    private final AiGatewayService gatewayService;
    private final ObjectMapper objectMapper;
    private final ConversationService conversationService;
    private final GuestSessionService guestSessionService;

    public AiGatewayController(
            AiGatewayService gatewayService,
            ObjectMapper objectMapper,
            ConversationService conversationService,
            GuestSessionService guestSessionService) {
        this.gatewayService = gatewayService;
        this.objectMapper = objectMapper;
        this.conversationService = conversationService;
        this.guestSessionService = guestSessionService;
    }

    /** 普通问答转发。 */
    @PostMapping(value = "/api/chat", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> chat(
            @RequestBody Map<String, Object> body,
            HttpServletRequest request,
            HttpServletResponse response) throws JsonProcessingException {
        ThreadContext threadContext = prepareThreadBody(body, request, response);
        HttpResponse<String> pythonResponse = gatewayService.forwardJson(
                "/api/chat",
                objectMapper.writeValueAsString(body),
                "POST");
        if (threadContext.userId() != null
                && pythonResponse.statusCode() >= 200
                && pythonResponse.statusCode() < 300) {
            String answer = objectMapper.readTree(pythonResponse.body()).path("answer").asText("");
            if (!answer.isBlank()) {
                conversationService.appendExchange(
                        threadContext.userId(),
                        threadContext.conversationId(),
                        String.valueOf(body.get("question")),
                        answer);
            }
        }
        return ResponseEntity.status(pythonResponse.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(pythonResponse.body());
    }

    /**
     * SSE 流式问答入口：浏览器只连接 Spring Boot，由 Spring Boot 再连接 Python RAG 服务。
     *
     * 这里不是等 Python 生成完整答案后再返回，而是先建立一条可持续写入的响应通道：
     * - 方法前半段准备请求上下文和 SSE 响应头；
     * - return 的 lambda 才是真正向浏览器写内容的异步执行体；
     * - Python 每产生一段 SSE 数据，AiGatewayService 就立即转发并 flush；
     * - 流结束后，Spring Boot 再从捕获到的 SSE 中提取完整答案并落库。
     *
     * 注意：不能直接返回 Python 的一次性字符串，否则前端无法获得首 token 低延迟体验。
     */
    @PostMapping(value = "/api/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public StreamingResponseBody chatStream(
            @RequestBody Map<String, Object> body,
            HttpServletRequest request,
            HttpServletResponse response)
            throws JsonProcessingException {
        // [1/5] 准备可信上下文：识别登录用户或游客，并统一生成 history 和 thread_id。
        // 登录用户的历史来自 Spring 数据库；游客使用签名 Cookie 隔离会话。
        ThreadContext threadContext = prepareThreadBody(body, request, response);

        // [2/5] 提前序列化最终请求体。
        // StreamingResponseBody 会在原请求线程之外执行，此时不再适合访问 RequestBody。
        String json = objectMapper.writeValueAsString(body);

        // [3/5] 建立 SSE 响应契约。
        // 下面的响应头共同保证：浏览器按事件流接收、代理不缓存、Nginx 不缓冲、压缩不延迟数据。
        response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setHeader("Cache-Control", "no-cache, no-transform");
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Content-Encoding", "identity");

        // [4/5] 返回异步响应体。
        // 方法此时可以先结束，lambda 后续在 Spring MVC 异步线程中执行；
        // outputStream 就是浏览器连接的响应输出流。
        return outputStream -> {
            // [5/5] 把 Python SSE 实时转发给浏览器。
            // pipePostStream() 内部逐块 write + flush；返回值是完整答案，仅用于会话落库。
            String answer = gatewayService.pipePostStream("/api/chat/stream", json, outputStream);

            // 流正常结束后保存本轮问答。
            // 这里只保存登录用户；游客的短期上下文由 Python Checkpoint 和签名 Cookie 维护。
            if (threadContext.userId() != null && !answer.isBlank()) {
                conversationService.appendExchange(
                        threadContext.userId(),
                        threadContext.conversationId(),
                        String.valueOf(body.get("question")),
                        answer);
            }
        };
    }

    /** 知识库上传转发：支持 file 或 text，upload_id 用于幂等。 */
    @PostMapping(value = "/api/upload", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> upload(
            @RequestParam(required = false) MultipartFile file,
            @RequestParam(required = false) String text,
            @RequestParam(name = "upload_id", required = false) String uploadId,
            HttpServletRequest request) throws IOException {
        Long userId = (Long) request.getAttribute(TokenAuthInterceptor.USER_ATTR);
        String username = (String) request.getAttribute(TokenAuthInterceptor.USERNAME_ATTR);
        HttpResponse<String> response = gatewayService.forwardUpload(
                "/api/upload",
                file,
                text,
                uploadId,
                userId,
                username);
        return ResponseEntity.status(response.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(response.body());
    }

    /** 管理员文档列表。 */
    @GetMapping(value = "/api/admin/documents", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminDocuments() {
        return forwardAdminJson("/api/admin/documents", null, "GET");
    }

    /** 管理员任务列表。 */
    @GetMapping(value = "/api/admin/tasks", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminTasks(
            @RequestParam(name = "document_id", required = false) Long documentId) {
        String path = "/api/admin/tasks"
                + (documentId == null ? "" : "?document_id=" + documentId);
        return forwardAdminJson(path, null, "GET");
    }

    @PostMapping(value = "/api/admin/documents/{documentId}/reindex", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminReindex(@PathVariable Long documentId) {
        return forwardAdminJson("/api/admin/documents/" + documentId + "/reindex", null, "POST");
    }

    @PostMapping(value = "/api/admin/documents/{documentId}/versions", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminVersionUpload(
            @PathVariable Long documentId,
            @RequestParam MultipartFile file,
            @RequestParam(name = "upload_id", required = false) String uploadId,
            HttpServletRequest request) throws IOException {
        Long userId = (Long) request.getAttribute(TokenAuthInterceptor.USER_ATTR);
        String username = (String) request.getAttribute(TokenAuthInterceptor.USERNAME_ATTR);
        HttpResponse<String> response = gatewayService.forwardUpload(
                "/api/admin/documents/" + documentId + "/versions",
                file,
                null,
                uploadId,
                userId,
                username);
        return ResponseEntity.status(response.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(response.body());
    }

    @GetMapping(value = "/api/admin/documents/{documentId}/versions", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminDocumentVersions(@PathVariable Long documentId) {
        return forwardAdminJson(
                "/api/admin/documents/" + documentId + "/versions",
                null,
                "GET");
    }

    @PostMapping(value = "/api/admin/documents/{documentId}/disable", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminDisable(@PathVariable Long documentId) {
        return forwardAdminJson("/api/admin/documents/" + documentId + "/disable", null, "POST");
    }

    @PostMapping(value = "/api/admin/documents/{documentId}/restore", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminRestore(@PathVariable Long documentId) {
        return forwardAdminJson("/api/admin/documents/" + documentId + "/restore", null, "POST");
    }

    @PostMapping(value = "/api/admin/documents/{documentId}/activate-version", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminActivateVersion(@PathVariable Long documentId) {
        return forwardAdminJson(
                "/api/admin/documents/" + documentId + "/activate-version",
                null,
                "POST");
    }

    @DeleteMapping(value = "/api/admin/documents/{documentId}", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> adminDelete(@PathVariable Long documentId) {
        return forwardAdminJson("/api/admin/documents/" + documentId, null, "DELETE");
    }

    /** 知识库分块数量查询转发。 */
    @GetMapping(value = "/api/knowledge/count", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> knowledgeCount() {
        HttpResponse<String> response = gatewayService.forwardJson("/api/knowledge/count", null, "GET");
        return ResponseEntity.status(response.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(response.body());
    }

    /** 删除当前用户或游客的短期记忆。 */
    @DeleteMapping(value = "/api/memory", produces = MediaType.APPLICATION_JSON_VALUE)
    public ResponseEntity<String> deleteMemory(
            @RequestParam(name = "conversation_id", required = false) String conversationId,
            HttpServletRequest request,
            HttpServletResponse response) {
        String threadId;
        Long userId = (Long) request.getAttribute(TokenAuthInterceptor.USER_ATTR);
        if (userId != null) {
            Long numericConversationId = parseConversationId(conversationId);
            if (numericConversationId == null) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.BAD_REQUEST,
                        "缺少 conversation_id");
            }
            conversationService.requireOwned(userId, numericConversationId);
            threadId = "user:" + userId + ":conversation:" + numericConversationId;
        } else {
            String guestId = guestSessionService.resolve(request, response);
            threadId = guestThreadId(guestId, conversationId);
        }

        HttpResponse<String> pythonResponse = gatewayService.forwardJson(
                "/api/memory/" + threadId,
                null,
                "DELETE");
        return ResponseEntity.status(pythonResponse.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(pythonResponse.body());
    }

    /**
     * 在调用 Python 前统一准备请求上下文。
     *
     * 这个方法是流式接口的“可信边界”：
     * 浏览器传来的内容只能作为问题参数，不能决定自己的用户身份、历史来源或 thread_id。
     *
     * 登录用户：
     * - 从 conversation_id 校验会话归属；
     * - 从 Spring 数据库读取最近历史；
     * - history_trusted=true，Python 可将其视为可信历史；
     * - thread_id 由服务端生成，浏览器无法伪造。
     *
     * 游客：
     * - 使用 GuestSessionService 验证或创建签名 Cookie；
     * - 不访问业务会话库；
     * - history_trusted=false，允许 Python 使用前端最近消息，但不能覆盖可信 Checkpoint。
     */
    private ThreadContext prepareThreadBody(
            Map<String, Object> body,
            HttpServletRequest request,
            HttpServletResponse response) {
        // 丢弃前端 thread_id，防止客户端伪造其他用户或其他会话的 Checkpoint 地址。
        // 最终 thread_id 必须由 Spring Boot 根据已认证身份重新生成。
        body.remove("thread_id");

        // OptionalTokenAuthInterceptor 已经在进入 Controller 前解析过可选 Token。
        // 登录成功时写入 USER_ATTR；没有 Token 或游客请求时该属性为空。
        Long userId = (Long) request.getAttribute(TokenAuthInterceptor.USER_ATTR);
        if (userId != null) {
            // 登录用户必须明确指定会话，且 conversation_id 必须能被解析。
            Long conversationId = parseConversationId(body.get("conversation_id"));
            if (conversationId == null) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.BAD_REQUEST,
                        "缺少 conversation_id");
            }

            // 从 Spring 会话库读取最近 20 条消息。
            // 前端即使携带 history，也会被这里的服务端历史覆盖。
            List<Map<String, Object>> history = conversationService.history(userId, conversationId, 20);
            body.put("history", history);
            body.put("history_trusted", true);

            // thread_id 同时包含用户和会话，确保不同用户、不同会话拥有独立 Checkpoint。
            body.put("thread_id", "user:" + userId + ":conversation:" + conversationId);
            return new ThreadContext(userId, conversationId);
        }

        // 游客没有业务会话库记录，使用签名 Cookie 生成稳定身份。
        // Cookie 只保存游客标识，真正的短期对话状态仍由 Python Checkpoint 维护。
        String guestId = guestSessionService.resolve(request, response);
        body.put("history_trusted", false);
        String conversationKey = body.get("conversation_id") == null
                ? null
                : String.valueOf(body.get("conversation_id"));

        // 游客 thread_id 也必须由服务端生成，并对 conversationKey 做字符清洗和长度限制。
        body.put("thread_id", guestThreadId(guestId, conversationKey));
        return new ThreadContext(null, null);
    }

    private static Long parseConversationId(Object value) {
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            try {
                return Long.parseLong(text.trim());
            } catch (NumberFormatException ignored) {
                return null;
            }
        }
        return null;
    }

    private static String guestThreadId(String guestId, String conversationId) {
        // 只保留适合放入内部标识的字符，避免前端传入特殊字符影响 Checkpoint key。
        String raw = conversationId == null ? "" : conversationId.trim();
        String safe = raw.replaceAll("[^A-Za-z0-9_-]", "_");
        if (safe.isBlank()) {
            safe = "default";
        }
        if (safe.length() > 64) {
            safe = safe.substring(0, 64);
        }
        return "guest:" + guestId + ":conversation:" + safe;
    }

    private ResponseEntity<String> forwardAdminJson(String path, String body, String method) {
        HttpResponse<String> response = gatewayService.forwardJson(path, body, method);
        return ResponseEntity.status(response.statusCode())
                .contentType(MediaType.APPLICATION_JSON)
                .body(response.body());
    }

    private record ThreadContext(Long userId, Long conversationId) {
    }
}
