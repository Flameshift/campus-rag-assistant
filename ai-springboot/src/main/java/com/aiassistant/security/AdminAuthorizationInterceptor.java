package com.aiassistant.security;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.servlet.HandlerInterceptor;

/** 管理员接口权限校验，必须运行在 TokenAuthInterceptor 之后。 */
@Component
public class AdminAuthorizationInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler)
            throws Exception {
        Object role = request.getAttribute(TokenAuthInterceptor.ROLE_ATTR);
        if ("ADMIN".equalsIgnoreCase(String.valueOf(role))) {
            return true;
        }
        response.setStatus(HttpStatus.FORBIDDEN.value());
        response.setContentType(MediaType.APPLICATION_JSON_VALUE);
        response.setCharacterEncoding("UTF-8");
        response.getWriter().write("{\"code\":\"403\",\"msg\":\"需要管理员权限\",\"data\":null}");
        return false;
    }
}
