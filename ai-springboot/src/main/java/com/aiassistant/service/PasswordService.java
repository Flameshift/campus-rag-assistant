package com.aiassistant.service;

import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.security.SecureRandom;
import java.util.HexFormat;
import javax.crypto.SecretKeyFactory;
import javax.crypto.spec.PBEKeySpec;
import org.springframework.stereotype.Service;

/**
 * 密码哈希服务。
 *
 * 使用 PBKDF2WithHmacSHA256 + 随机盐，和 Python 端思路一致；
 * 由于两端不共享用户表，盐与哈希算法无需互相兼容。
 */
@Service
public class PasswordService {

    private static final int ITERATIONS = 200_000;
    private static final int KEY_LENGTH = 256;
    private static final SecureRandom RANDOM = new SecureRandom();

    /** 生成随机盐并计算密码哈希，返回 "盐:哈希" 便于单列存储。 */
    public String hash(String rawPassword) {
        byte[] salt = new byte[16];
        RANDOM.nextBytes(salt);
        return encodeHex(salt) + ":" + pbkdf2(rawPassword, salt);
    }

    /** 校验密码：从存储串中拆出盐值并重新计算。 */
    public boolean matches(String rawPassword, String stored) {
        String[] parts = stored.split(":", 2);
        if (parts.length != 2) {
            return false;
        }
        byte[] salt = decodeHex(parts[0]);
        String expected = parts[1];
        return MessageDigest.isEqual(pbkdf2(rawPassword, salt).getBytes(), expected.getBytes());
    }

    private String pbkdf2(String password, byte[] salt) {
        try {
            PBEKeySpec spec = new PBEKeySpec(password.toCharArray(), salt, ITERATIONS, KEY_LENGTH);
            SecretKeyFactory factory = SecretKeyFactory.getInstance("PBKDF2WithHmacSHA256");
            return encodeHex(factory.generateSecret(spec).getEncoded());
        } catch (Exception ex) {
            throw new IllegalStateException("密码哈希计算失败", ex);
        }
    }

    private static String encodeHex(byte[] bytes) {
        return HexFormat.of().formatHex(bytes);
    }

    private static byte[] decodeHex(String hex) {
        return HexFormat.of().parseHex(hex);
    }
}
