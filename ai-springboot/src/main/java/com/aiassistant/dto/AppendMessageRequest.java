package com.aiassistant.dto;

import jakarta.validation.constraints.NotBlank;

/** 追加消息请求体。 */
public record AppendMessageRequest(
        @NotBlank String role,
        @NotBlank String content) {
}
