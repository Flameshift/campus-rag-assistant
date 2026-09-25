package com.aiassistant.model;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.GeneratedValue;
import jakarta.persistence.GenerationType;
import jakarta.persistence.Id;
import jakarta.persistence.Table;
import java.time.LocalDateTime;

/**
 * 注册用户。
 *
 * 密码只保存加盐哈希，不保存明文。
 */
@Entity
@Table(name = "users")
public class User {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(nullable = false, unique = true, length = 64)
    private String username;

    /** 用户角色：USER / ADMIN。旧数据为空时按 USER 处理。 */
    @Column(length = 20)
    private String role = "USER";

    /** PBKDF2-SHA256 哈希结果。 */
    @Column(nullable = false, length = 128)
    private String passwordHash;

    /** 生成哈希时使用的随机盐值。 */
    @Column(nullable = false, length = 64)
    private String salt;

    @Column(nullable = false)
    private LocalDateTime createdAt = LocalDateTime.now();

    public Long getId() {
        return id;
    }

    public String getUsername() {
        return username;
    }

    public void setUsername(String username) {
        this.username = username;
    }

    public String getRole() {
        return role == null || role.isBlank() ? "USER" : role;
    }

    public void setRole(String role) {
        this.role = role == null || role.isBlank() ? "USER" : role;
    }

    public String getPasswordHash() {
        return passwordHash;
    }

    public void setPasswordHash(String passwordHash) {
        this.passwordHash = passwordHash;
    }

    public String getSalt() {
        return salt;
    }

    public void setSalt(String salt) {
        this.salt = salt;
    }

    public LocalDateTime getCreatedAt() {
        return createdAt;
    }
}
