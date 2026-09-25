package com.aiassistant.dto;

import java.time.LocalDateTime;
import java.util.List;

/** 会话响应：包含标题、时间与全部消息。 */
public record ConversationResponse(
        Long id,
        String title,
        LocalDateTime createdAt,
        LocalDateTime updatedAt,
        List<MessageResponse> messages) {
}
