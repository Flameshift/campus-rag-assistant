package com.aiassistant.repository;

import com.aiassistant.model.AuthToken;

import java.time.LocalDateTime;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.Modifying;
import org.springframework.data.jpa.repository.Query;
import org.springframework.data.repository.query.Param;

/** 登录令牌数据访问层。 */
public interface AuthTokenRepository extends JpaRepository<AuthToken, Long> {

    Optional<AuthToken> findByToken(String token);

    void deleteByUserId(Long userId);

    @Modifying
    @Query("delete from AuthToken t where t.expiresAt < :now")
    int deleteExpiredBefore(@Param("now") LocalDateTime now);
}
