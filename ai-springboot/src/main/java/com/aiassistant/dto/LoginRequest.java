package com.aiassistant.dto;

import jakarta.validation.constraints.NotBlank;

/** 登录请求体。 */
public record LoginRequest(@NotBlank String username, @NotBlank String password) {
}
