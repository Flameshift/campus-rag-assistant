package com.aiassistant.repository;

import com.aiassistant.model.User;
import java.util.Optional;
import org.springframework.data.jpa.repository.JpaRepository;

/** 用户数据访问层。 */
public interface UserRepository extends JpaRepository<User, Long> {

    Optional<User> findByUsername(String username);
}
