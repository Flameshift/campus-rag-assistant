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

    /** SSE 流式问答转发：把 Python 返回流原样透传给前端。 */
    @PostMapping(value = "/api/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public StreamingResponseBody chatStream(
            @RequestBody Map<String, Object> body,
            HttpServletRequest request,
            HttpServletResponse response)
            throws JsonProcessingException {
        ThreadContext threadContext = prepareThreadBody(body, request, response);
        String json = objectMapper.writeValueAsString(body);
        response.setContentType(MediaType.TEXT_EVENT_STREAM_VALUE);
        response.setCharacterEncoding(StandardCharsets.UTF_8.name());
        response.setHeader("Cache-Control", "no-cache, no-transform");
        response.setHeader("X-Accel-Buffering", "no");
        response.setHeader("Content-Encoding", "identity");
        return outputStream -> {
            String answer = gatewayService.pipePostStream("/api/chat/stream", json, outputStream);
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
     * 服务端生成 thread_id。登录用户强制校验会话归属，游客使用签名 Cookie。
     */
    private ThreadContext prepareThreadBody(
            Map<String, Object> body,
            HttpServletRequest request,
            HttpServletResponse response) {
        body.remove("thread_id");
        Long userId = (Long) request.getAttribute(TokenAuthInterceptor.USER_ATTR);
        if (userId != null) {
            Long conversationId = parseConversationId(body.get("conversation_id"));
            if (conversationId == null) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.BAD_REQUEST,
                        "缺少 conversation_id");
            }
            List<Map<String, Object>> history = conversationService.history(userId, conversationId, 20);
            body.put("history", history);
            body.put("history_trusted", true);
            body.put("thread_id", "user:" + userId + ":conversation:" + conversationId);
            return new ThreadContext(userId, conversationId);
        }

        String guestId = guestSessionService.resolve(request, response);
        body.put("history_trusted", false);
        String conversationKey = body.get("conversation_id") == null
                ? null
                : String.valueOf(body.get("conversation_id"));
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
