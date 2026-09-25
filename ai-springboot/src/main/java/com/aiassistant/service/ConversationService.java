package com.aiassistant.service;

import com.aiassistant.dto.AppendMessageRequest;
import com.aiassistant.dto.ConversationResponse;
import com.aiassistant.dto.MessageResponse;
import com.aiassistant.model.Conversation;
import com.aiassistant.model.Message;
import com.aiassistant.repository.ConversationRepository;
import com.aiassistant.repository.MessageRepository;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

/**
 * 会话与消息历史服务。
 *
 * 所有操作都按 userId 过滤，保证只能访问自己的会话。
 */
@Service
public class ConversationService {

    private static final String DEFAULT_TITLE = "新对话";

    private final ConversationRepository conversationRepository;
    private final MessageRepository messageRepository;

    public ConversationService(
            ConversationRepository conversationRepository,
            MessageRepository messageRepository) {
        this.conversationRepository = conversationRepository;
        this.messageRepository = messageRepository;
    }

    @Transactional(readOnly = true)
    public List<ConversationResponse> list(Long userId) {
        return conversationRepository.findByUserIdOrderByUpdatedAtDesc(userId).stream()
                .map(this::toResponse)
                .toList();
    }

    @Transactional
    public ConversationResponse create(Long userId, String title) {
        Conversation conversation = new Conversation();
        conversation.setUserId(userId);
        conversation.setTitle(title == null || title.isBlank() ? DEFAULT_TITLE : title.trim());
        conversationRepository.save(conversation);
        return toResponse(conversation);
    }

    @Transactional(readOnly = true)
    public ConversationResponse get(Long userId, Long conversationId) {
        return toResponse(requireOwnedInternal(userId, conversationId));
    }

    @Transactional(readOnly = true)
    public List<Map<String, Object>> history(Long userId, Long conversationId, int limit) {
        requireOwned(userId, conversationId);
        List<Message> messages = messageRepository.findByConversationIdOrderByIdAsc(conversationId);
        int fromIndex = limit > 0 ? Math.max(0, messages.size() - limit) : 0;
        return messages.subList(fromIndex, messages.size()).stream()
                .map(message -> {
                    Map<String, Object> item = new LinkedHashMap<>();
                    item.put("role", message.getRole());
                    item.put("content", message.getContent());
                    return item;
                })
                .toList();
    }

    @Transactional(readOnly = true)
    public void requireOwned(Long userId, Long conversationId) {
        requireOwnedInternal(userId, conversationId);
    }

    @Transactional
    public ConversationResponse appendMessage(Long userId, Long conversationId, AppendMessageRequest request) {
        Conversation conversation = requireOwnedInternal(userId, conversationId);

        if (DEFAULT_TITLE.equals(conversation.getTitle()) && "user".equals(request.role())) {
            String title = request.content().strip().replace("\n", " ");
            conversation.setTitle(title.length() > 16 ? title.substring(0, 16) + "…" : title);
        }
        conversation.setUpdatedAt(LocalDateTime.now());
        conversationRepository.save(conversation);

        Message message = new Message();
        message.setConversationId(conversation.getId());
        message.setRole(request.role());
        message.setContent(request.content());
        messageRepository.save(message);

        return toResponse(conversation);
    }

    @Transactional
    public void appendExchange(Long userId, Long conversationId, String question, String answer) {
        Conversation conversation = requireOwnedInternal(userId, conversationId);
        String normalizedQuestion = question == null ? "" : question.strip();
        String normalizedAnswer = answer == null ? "" : answer.strip();
        if (normalizedQuestion.isEmpty() || normalizedAnswer.isEmpty()) {
            return;
        }

        if (DEFAULT_TITLE.equals(conversation.getTitle())) {
            String title = normalizedQuestion.replace("\n", " ");
            conversation.setTitle(title.length() > 16 ? title.substring(0, 16) + "…" : title);
        }
        conversation.setUpdatedAt(LocalDateTime.now());
        conversationRepository.save(conversation);

        Message userMessage = new Message();
        userMessage.setConversationId(conversation.getId());
        userMessage.setRole("user");
        userMessage.setContent(normalizedQuestion);
        messageRepository.save(userMessage);

        Message assistantMessage = new Message();
        assistantMessage.setConversationId(conversation.getId());
        assistantMessage.setRole("assistant");
        assistantMessage.setContent(normalizedAnswer);
        messageRepository.save(assistantMessage);
    }

    @Transactional
    public void delete(Long userId, Long conversationId) {
        Conversation conversation = requireOwnedInternal(userId, conversationId);
        List<Message> messages = messageRepository.findByConversationIdOrderByIdAsc(conversationId);
        messageRepository.deleteAll(messages);
        conversationRepository.delete(conversation);
    }

    private Conversation requireOwnedInternal(Long userId, Long conversationId) {
        return conversationRepository.findByIdAndUserId(conversationId, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
    }

    private ConversationResponse toResponse(Conversation conversation) {
        List<MessageResponse> messages = messageRepository
                .findByConversationIdOrderByIdAsc(conversation.getId())
                .stream()
                .map(message -> new MessageResponse(
                        message.getId(),
                        message.getRole(),
                        message.getContent(),
                        message.getCreatedAt()))
                .toList();
        return new ConversationResponse(
                conversation.getId(),
                conversation.getTitle(),
                conversation.getCreatedAt(),
                conversation.getUpdatedAt(),
                messages);
    }
}
