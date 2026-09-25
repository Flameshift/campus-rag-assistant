package com.aiassistant.dto;

/** 新建会话请求体；title 缺省由后端设置为“新对话”。 */
public record CreateConversationRequest(String title) {

    public String effectiveTitle() {
        return title == null || title.isBlank() ? "新对话" : title.trim();
    }
}
