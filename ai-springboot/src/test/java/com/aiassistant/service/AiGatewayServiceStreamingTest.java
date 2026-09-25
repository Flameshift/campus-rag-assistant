package com.aiassistant.service;

import static org.assertj.core.api.Assertions.assertThat;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.sun.net.httpserver.HttpServer;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import org.junit.jupiter.api.Test;

class AiGatewayServiceStreamingTest {

    @Test
    void flushesEachStreamingChunkToTheResponse() throws Exception {
        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        server.createContext("/api/chat/stream", exchange -> {
            exchange.getResponseHeaders().add("Content-Type", "text/event-stream");
            exchange.sendResponseHeaders(200, 0);
            try (OutputStream output = exchange.getResponseBody()) {
                writeToken(output, "A");
                pauseBetweenChunks();
                writeToken(output, "B");
            }
        });
        server.start();

        try {
            AiGatewayService service = new AiGatewayService(
                    "http://127.0.0.1:" + server.getAddress().getPort(),
                    "test-secret",
                    new ObjectMapper());
            TrackingOutputStream sink = new TrackingOutputStream();

            String answer = service.pipePostStream(
                    "/api/chat/stream",
                    "{\"question\":\"test\"}",
                    sink);

            assertThat(answer).isEqualTo("AB");
            assertThat(sink.flushCount).isGreaterThanOrEqualTo(2);
        } finally {
            server.stop(0);
        }
    }

    private static void writeToken(OutputStream output, String content) throws IOException {
        String event = "data: {\"type\":\"token\",\"content\":\""
                + content
                + "\"}\n\n";
        output.write(event.getBytes(StandardCharsets.UTF_8));
        output.flush();
    }

    private static void pauseBetweenChunks() throws IOException {
        try {
            Thread.sleep(80);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IOException("stream test interrupted", exception);
        }
    }

    private static final class TrackingOutputStream extends ByteArrayOutputStream {
        private int flushCount;

        @Override
        public void flush() throws IOException {
            flushCount++;
            super.flush();
        }
    }
}
