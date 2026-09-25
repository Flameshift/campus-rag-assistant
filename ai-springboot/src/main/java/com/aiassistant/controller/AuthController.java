package com.aiassistant.controller;

import com.aiassistant.dto.AuthResponse;
import com.aiassistant.dto.LoginRequest;
import com.aiassistant.dto.RegisterRequest;
import com.aiassistant.dto.UserResponse;
import com.aiassistant.common.Result;
import com.aiassistant.security.TokenAuthInterceptor;
import com.aiassistant.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestAttribute;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/** 注册 / 登录 / 登出 / 当前用户。 */
@RestController
@RequestMapping("/api/auth")
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public Result<AuthResponse> register(@Valid @RequestBody RegisterRequest request) {
        return Result.success(authService.register(request));
    }

    @PostMapping("/login")
    public Result<AuthResponse> login(@Valid @RequestBody LoginRequest request) {
        return Result.success(authService.login(request));
    }

    /** 当前登录用户（由拦截器校验 Token）。 */
    @GetMapping("/me")
    public Result<UserResponse> me(@RequestAttribute(TokenAuthInterceptor.USERNAME_ATTR) String username,
                                   @RequestAttribute(TokenAuthInterceptor.USER_ATTR) Long userId,
                                   @RequestAttribute(TokenAuthInterceptor.ROLE_ATTR) String role) {
        return Result.success(new UserResponse(userId, username, role));
    }

    /** 登出：删除当前 Bearer Token。 */
    @PostMapping("/logout")
    public Result<Void> logout(HttpServletRequest request) {
        String header = request.getHeader("Authorization");
        authService.logout(header.substring(7).trim());
        return Result.success();
    }
}
