package com.aiassistant.security;

import static org.assertj.core.api.Assertions.assertThat;

import org.junit.jupiter.api.Test;

class GuestSessionServiceTest {

    private final GuestSessionService service = new GuestSessionService("test-secret", 72, false);

    @Test
    void validSignedTokenIsAccepted() {
        String token = service.createToken("guest-123");

        assertThat(service.verifyToken(token)).contains("guest-123");
    }

    @Test
    void tamperedTokenIsRejected() {
        String token = service.createToken("guest-123");
        String tampered = token.substring(0, token.length() - 2) + "xx";

        assertThat(service.verifyToken(tampered)).isEmpty();
    }

    @Test
    void malformedTokenIsRejected() {
        assertThat(service.verifyToken("invalid")).isEmpty();
        assertThat(service.verifyToken(null)).isEmpty();
    }
}
