package com.aiassistant.dto;

import java.time.LocalDateTime;

/** 会话消息响应。 */
public record MessageResponse(Long id, String role, String content, LocalDateTime createdAt) {
}
