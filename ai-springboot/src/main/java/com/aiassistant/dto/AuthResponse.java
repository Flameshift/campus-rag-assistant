package com.aiassistant.dto;

/** 登录/注册成功后的响应：前端保存 token 与用户信息。 */
public record AuthResponse(String token, UserResponse user) {
}
