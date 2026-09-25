package com.aiassistant;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;
import org.springframework.scheduling.annotation.EnableScheduling;

/**
 * Spring Boot 启动类。
 *
 * 职责：
 * 1. 提供注册/登录/登出与 Token 鉴权；
 * 2. 管理会话与消息历史；
 * 3. 作为 AI 网关，把知识库上传 / 问答 / 流式请求转发给 Python 服务。
 */
@EnableScheduling
@SpringBootApplication
public class AiSpringbootApplication {

    public static void main(String[] args) {
        SpringApplication.run(AiSpringbootApplication.class, args);
    }
}
