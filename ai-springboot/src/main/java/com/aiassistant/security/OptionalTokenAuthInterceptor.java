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
        // /api/chat/stream 同时服务登录用户和游客，因此缺少 Authorization 时不能直接拒绝。
        // 交给 Controller 的 prepareThreadBody() 继续创建游客上下文。
        String authorization = request.getHeader("Authorization");
        if (authorization == null || authorization.isBlank()) {
            return true;
        }

        // 一旦携带 Token，就必须满足 Bearer 格式；格式错误不会被当成游客静默降级。
        if (!authorization.toLowerCase().startsWith("bearer ")) {
            return reject(response, "Authorization 格式错误");
        }

        try {
            // 校验 Token 后把用户身份写入 Request Attribute。
            // Controller 通过 USER_ATTR 区分登录用户；游客请求不会设置该属性。
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
