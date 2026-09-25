package com.aiassistant.task;

import com.aiassistant.service.AuthService;
import lombok.extern.slf4j.Slf4j;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Slf4j
@Component
public class TokenCleanupTask {

    private final AuthService authService;

    public TokenCleanupTask(AuthService authService) {
        this.authService = authService;
    }

    @Scheduled(cron = "${auth.token-cleanup-cron:0 0 3 * * *}")
    public void cleanExpiredTokens() {
        int deleted = authService.cleanExpiredTokens();
        log.info("清理过期 Token 数量: {}", deleted);
    }
}