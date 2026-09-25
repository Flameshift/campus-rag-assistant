package com.aiassistant.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.aiassistant.model.AuthToken;
import com.aiassistant.repository.AuthTokenRepository;
import java.time.LocalDateTime;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;

/**
 * 过期 Token 清理测试。
 *
 * 使用内存 H2，避免影响本地 data/ai_history 文件数据库。
 */
@SpringBootTest(properties = {
        "spring.datasource.url=jdbc:h2:mem:token_cleanup_test;MODE=MySQL;DB_CLOSE_DELAY=-1",
        "spring.jpa.hibernate.ddl-auto=create-drop"
})
class AuthServiceCleanupTest {

    @Autowired
    private AuthService authService;

    @Autowired
    private AuthTokenRepository tokenRepository;

    @BeforeEach
    void setUp() {
        tokenRepository.deleteAll();
    }

    @Test
    void deletesOnlyExpiredTokens() {
        tokenRepository.save(token("expired-token", LocalDateTime.now().minusDays(1)));
        tokenRepository.save(token("valid-token", LocalDateTime.now().plusDays(1)));

        int deleted = authService.cleanExpiredTokens();

        assertThat(deleted).isEqualTo(1);
        assertThat(tokenRepository.findByToken("expired-token")).isEmpty();
        assertThat(tokenRepository.findByToken("valid-token")).isPresent();
    }

    private static AuthToken token(String value, LocalDateTime expiresAt) {
        AuthToken token = new AuthToken();
        token.setToken(value);
        token.setUserId(999L);
        token.setExpiresAt(expiresAt);
        return token;
    }
}
