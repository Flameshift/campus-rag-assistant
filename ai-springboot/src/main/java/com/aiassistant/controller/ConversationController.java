package com.aiassistant.controller;

import com.aiassistant.dto.AppendMessageRequest;
import com.aiassistant.dto.ConversationResponse;
import com.aiassistant.dto.CreateConversationRequest;
import com.aiassistant.common.Result;
import com.aiassistant.security.TokenAuthInterceptor;
import com.aiassistant.service.ConversationService;
import jakarta.validation.Valid;
import java.util.List;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 会话历史接口：全部需要登录，Token 由拦截器解析为 userId。
 */
@RestController
@RequestMapping("/api/conversations")
public class ConversationController {

    private final ConversationService conversationService;

    public ConversationController(ConversationService conversationService) {
        this.conversationService = conversationService;
    }

    @GetMapping
    public Result<List<ConversationResponse>> list(@RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId) {
        return Result.success(conversationService.list(userId));
    }

    @PostMapping
    public Result<ConversationResponse> create(
            @RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId,
            @RequestBody(required = false) CreateConversationRequest request) {
        return Result.success(conversationService.create(userId, request == null ? null : request.title()));
    }

    @GetMapping("/{id}")
    public Result<ConversationResponse> get(
            @RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId,
            @PathVariable Long id) {
        return Result.success(conversationService.get(userId, id));
    }

    @PostMapping("/{id}/messages")
    public Result<ConversationResponse> appendMessage(
            @RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId,
            @PathVariable Long id,
            @Valid @RequestBody AppendMessageRequest request) {
        return Result.success(conversationService.appendMessage(userId, id, request));
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(
            @RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId,
            @PathVariable Long id) {
        conversationService.delete(userId, id);
        return Result.success();
    }
}
