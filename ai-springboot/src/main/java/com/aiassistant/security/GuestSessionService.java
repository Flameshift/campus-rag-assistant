package com.aiassistant.security;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.Base64;
import java.util.Optional;
import java.util.UUID;
import javax.crypto.Mac;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

/**
 * 游客短期会话：使用 HMAC 签名 Cookie，避免客户端伪造 thread_id。
 */
@Service
public class GuestSessionService {

    public static final String COOKIE_NAME = "ai_guest_session";

    private final byte[] secret;
    private final long ttlSeconds;
    private final boolean secureCookie;

    public GuestSessionService(
            @Value("${security.guest-session-secret:local-dev-guest-session-secret}") String secret,
            @Value("${security.guest-session-ttl-hours:72}") long ttlHours,
            @Value("${security.guest-session-secure:false}") boolean secureCookie) {
        this.secret = secret.getBytes(StandardCharsets.UTF_8);
        this.ttlSeconds = Math.max(1, ttlHours) * 3600;
        this.secureCookie = secureCookie;
    }

    /** 读取有效 Cookie；不存在或无效时创建新游客会话并写入 Cookie。 */
    public String resolve(HttpServletRequest request, HttpServletResponse response) {
        // 优先复用浏览器已有且签名有效的游客身份，使同一浏览器能继续访问自己的 Checkpoint。
        String token = findCookie(request);
        Optional<String> verified = verifyToken(token);
        if (verified.isPresent()) {
            return verified.get();
        }

        // Cookie 缺失、过期或签名不合法时创建新游客身份。
        // HttpOnly 防止脚本读取，SameSite=Lax 降低跨站请求伪造风险。
        String sessionId = UUID.randomUUID().toString().replace("-", "");
        String newToken = createToken(sessionId);
        String cookie = COOKIE_NAME + "=" + newToken
                + "; Path=/; Max-Age=" + ttlSeconds
                + "; HttpOnly; SameSite=Lax"
                + (secureCookie ? "; Secure" : "");
        response.addHeader("Set-Cookie", cookie);
        return sessionId;
    }

    String createToken(String sessionId) {
        long expiresAt = Instant.now().getEpochSecond() + ttlSeconds;
        String payload = sessionId + "." + expiresAt;
        return payload + "." + sign(payload);
    }

    Optional<String> verifyToken(String token) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }

        // 格式固定为 sessionId.expiresAt.signature，三段必须完整。
        String[] parts = token.split("\\.");
        if (parts.length != 3) {
            return Optional.empty();
        }
        try {
            // 先检查过期时间，再验证签名，降低无效 Token 进入后续流程的概率。
            long expiresAt = Long.parseLong(parts[1]);
            if (expiresAt < Instant.now().getEpochSecond()) {
                return Optional.empty();
            }

            // 重新计算签名，并使用常量时间比较，避免客户端伪造游客身份。
            String payload = parts[0] + "." + parts[1];
            byte[] expected = sign(payload).getBytes(StandardCharsets.UTF_8);
            byte[] actual = parts[2].getBytes(StandardCharsets.UTF_8);
            if (!MessageDigest.isEqual(expected, actual)) {
                return Optional.empty();
            }
            return Optional.of(parts[0]);
        } catch (NumberFormatException ex) {
            return Optional.empty();
        }
    }

    private String sign(String payload) {
        try {
            Mac mac = Mac.getInstance("HmacSHA256");
            mac.init(new SecretKeySpec(secret, "HmacSHA256"));
            return Base64.getUrlEncoder().withoutPadding()
                    .encodeToString(mac.doFinal(payload.getBytes(StandardCharsets.UTF_8)));
        } catch (Exception ex) {
            throw new IllegalStateException("游客会话签名失败", ex);
        }
    }

    private static String findCookie(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        for (Cookie cookie : cookies) {
            if (COOKIE_NAME.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }
}
