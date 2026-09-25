package com.aiassistant.security;

import com.aiassistant.model.User;
import com.aiassistant.service.AuthService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/**
 * 登录鉴权拦截器。
 *
 * 只负责解析 Authorization: Bearer <token> 并校验；
 * 通过后把 userId 放入请求属性，控制器用 @RequestAttribute 读取。
 */
@Component
public class TokenAuthInterceptor implements HandlerInterceptor {

    public static final String USER_ATTR = "currentUserId";
    public static final String USERNAME_ATTR = "currentUsername";
    public static final String ROLE_ATTR = "currentUserRole";

    private final AuthService authService;

    public TokenAuthInterceptor(AuthService authService) {
        this.authService = authService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        String authorization = request.getHeader("Authorization");
        if (authorization == null || !authorization.toLowerCase().startsWith("bearer ")) {
            return reject(response, "未登录");
        }

        try {
            User user = authService.requireUserByToken(authorization.substring(7).trim());
            request.setAttribute(USER_ATTR, user.getId());
            request.setAttribute(USERNAME_ATTR, user.getUsername());
            request.setAttribute(ROLE_ATTR, user.getRole());
            return true;
        } catch (RuntimeException ex) {
            return reject(response, ex.getMessage() == null ? "登录已失效" : ex.getMessage());
        }
    }

    private static boolean reject(HttpServletResponse response, String message) throws Exception {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        // 与 GlobalExceptionHandler 保持一致的 Result 结构。
        response.getWriter().write("{\"code\":\"401\",\"msg\":\"" + message + "\",\"data\":null}");
        return false;
    }
}
