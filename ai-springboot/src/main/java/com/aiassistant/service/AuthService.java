package com.aiassistant.service;

import com.aiassistant.dto.AuthResponse;
import com.aiassistant.dto.LoginRequest;
import com.aiassistant.dto.RegisterRequest;
import com.aiassistant.dto.UserResponse;
import com.aiassistant.model.AuthToken;
import com.aiassistant.model.User;
import com.aiassistant.repository.AuthTokenRepository;
import com.aiassistant.repository.UserRepository;
import java.time.LocalDateTime;
import java.util.UUID;

import jakarta.transaction.Transactional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

/**
 * 用户注册、登录、令牌管理。
 *
 * 令牌保存在 auth_tokens 表，登出即删除，天然支持吊销。
 */
@Service
public class AuthService {

    private final UserRepository userRepository;
    private final AuthTokenRepository tokenRepository;
    private final PasswordService passwordService;
    private final int tokenTtlDays;
    private final String bootstrapAdminUsername;

    public AuthService(
            UserRepository userRepository,
            AuthTokenRepository tokenRepository,
            PasswordService passwordService,
            @Value("${auth.token-ttl-days:7}") int tokenTtlDays,
            @Value("${auth.bootstrap-admin-username:admin}") String bootstrapAdminUsername) {
        this.userRepository = userRepository;
        this.tokenRepository = tokenRepository;
        this.passwordService = passwordService;
        this.tokenTtlDays = tokenTtlDays;
        this.bootstrapAdminUsername = bootstrapAdminUsername == null
                ? ""
                : bootstrapAdminUsername.trim();
    }

    public AuthResponse register(RegisterRequest request) {
        if (userRepository.findByUsername(request.username()).isPresent()) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "用户名已存在");
        }

        User user = new User();
        user.setUsername(request.username().trim());
        // PasswordService 返回 "盐:哈希"，数据库同时保留盐字段方便后续排查。
        String hashed = passwordService.hash(request.password());
        user.setPasswordHash(hashed);
        user.setSalt(hashed.split(":", 2)[0]);
        user.setRole(
                user.getUsername().equalsIgnoreCase(bootstrapAdminUsername)
                        ? "ADMIN"
                        : "USER");
        userRepository.save(user);

        return new AuthResponse(issueToken(user), toUserResponse(user));
    }

    public AuthResponse login(LoginRequest request) {
        User user = userRepository.findByUsername(request.username().trim())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误"));
        if (!passwordService.matches(request.password(), user.getPasswordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }
        return new AuthResponse(issueToken(user), toUserResponse(user));
    }

    /** 校验 Token 并返回所属用户；供鉴权拦截器使用。 */
    public User requireUserByToken(String token) {
        AuthToken authToken = tokenRepository.findByToken(token)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "登录已失效"));
        if (authToken.getExpiresAt().isBefore(LocalDateTime.now())) {
            tokenRepository.delete(authToken);
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "登录已过期");
        }
        return userRepository.findById(authToken.getUserId())
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户不存在"));
    }

    /** 删除当前 Token，实现登出。 */
    public void logout(String token) {
        tokenRepository.findByToken(token).ifPresent(tokenRepository::delete);
    }

    public UserResponse me(User user) {
        return toUserResponse(user);
    }

    private String issueToken(User user) {
        String token = UUID.randomUUID().toString().replace("-", "") + UUID.randomUUID().toString().replace("-", "");
        AuthToken authToken = new AuthToken();
        authToken.setToken(token);
        authToken.setUserId(user.getId());
        authToken.setExpiresAt(LocalDateTime.now().plusDays(tokenTtlDays));
        tokenRepository.save(authToken);
        return token;
    }
    @Transactional
    public int cleanExpiredTokens() {
        return tokenRepository.deleteExpiredBefore(LocalDateTime.now());
    }

    private static UserResponse toUserResponse(User user) {
        return new UserResponse(user.getId(), user.getUsername(), user.getRole());
    }
}
