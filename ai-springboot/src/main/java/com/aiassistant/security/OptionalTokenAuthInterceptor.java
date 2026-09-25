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
 * 可选鉴权拦截器：有 Token 时解析用户，无 Token 时按游客继续。
 */
@Component
public class OptionalTokenAuthInterceptor implements HandlerInterceptor {

    private final AuthService authService;

    public OptionalTokenAuthInterceptor(AuthService authService) {
        this.authService = authService;
    }

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        String authorization = request.getHeader("Authorization");
        if (authorization == null || authorization.isBlank()) {
            return true;
        }
        if (!authorization.toLowerCase().startsWith("bearer ")) {
            return reject(response, "Authorization 格式错误");
        }

        try {
            User user = authService.requireUserByToken(authorization.substring(7).trim());
            request.setAttribute(TokenAuthInterceptor.USER_ATTR, user.getId());
            request.setAttribute(TokenAuthInterceptor.USERNAME_ATTR, user.getUsername());
            request.setAttribute(TokenAuthInterceptor.ROLE_ATTR, user.getRole());
            return true;
        } catch (RuntimeException ex) {
            return reject(response, ex.getMessage() == null ? "登录已失效" : ex.getMessage());
        }
    }

    private static boolean reject(HttpServletResponse response, String message) throws Exception {
        response.setStatus(HttpStatus.UNAUTHORIZED.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write("{\"code\":\"401\",\"msg\":\"" + message + "\",\"data\":null}");
        return false;
    }
}
