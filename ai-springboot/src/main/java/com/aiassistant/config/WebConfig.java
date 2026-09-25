package com.aiassistant.config;

import com.aiassistant.security.AdminAuthorizationInterceptor;
import com.aiassistant.security.TokenAuthInterceptor;
import com.aiassistant.security.OptionalTokenAuthInterceptor;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.servlet.config.annotation.CorsRegistry;
import org.springframework.web.servlet.config.annotation.InterceptorRegistry;
import org.springframework.web.servlet.config.annotation.WebMvcConfigurer;

/**
 * Web 配置：注册鉴权拦截器与跨域规则。
 */
@Configuration
public class WebConfig implements WebMvcConfigurer {

    private final TokenAuthInterceptor tokenAuthInterceptor;
    private final OptionalTokenAuthInterceptor optionalTokenAuthInterceptor;
    private final AdminAuthorizationInterceptor adminAuthorizationInterceptor;

    public WebConfig(
            TokenAuthInterceptor tokenAuthInterceptor,
            OptionalTokenAuthInterceptor optionalTokenAuthInterceptor,
            AdminAuthorizationInterceptor adminAuthorizationInterceptor) {
        this.tokenAuthInterceptor = tokenAuthInterceptor;
        this.optionalTokenAuthInterceptor = optionalTokenAuthInterceptor;
        this.adminAuthorizationInterceptor = adminAuthorizationInterceptor;
    }

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        // 只有“业务数据”接口需要登录；AI 网关接口允许游客访问。
        registry.addInterceptor(tokenAuthInterceptor)
                .addPathPatterns(
                        "/api/conversations/**",
                        "/api/admin/**",
                        "/api/upload",
                        "/api/auth/me",
                        "/api/auth/logout");
        registry.addInterceptor(adminAuthorizationInterceptor)
                .addPathPatterns(
                        "/api/admin/**",
                        "/api/upload");
        registry.addInterceptor(optionalTokenAuthInterceptor)
                .addPathPatterns(
                        "/api/chat",
                        "/api/chat/stream",
                        "/api/memory");
    }

    @Override
    public void addCorsMappings(CorsRegistry registry) {
        registry.addMapping("/**")
                .allowedOriginPatterns("http://localhost:*", "http://127.0.0.1:*")
                .allowedMethods("*")
                .allowedHeaders("*")
                .allowCredentials(true);
    }
}
