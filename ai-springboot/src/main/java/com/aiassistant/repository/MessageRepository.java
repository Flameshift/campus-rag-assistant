package com.aiassistant.repository;

import com.aiassistant.model.Message;
import java.util.List;
import org.springframework.data.jpa.repository.JpaRepository;

/** 消息数据访问层。 */
public interface MessageRepository extends JpaRepository<Message, Long> {

    List<Message> findByConversationIdOrderByCreatedAtAsc(Long conversationId);

    List<Message> findByConversationIdOrderByIdAsc(Long conversationId);

    long countByConversationId(Long conversationId);
}
