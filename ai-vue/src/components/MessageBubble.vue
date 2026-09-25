<script setup>
import { Bot } from '@lucide/vue'

defineProps({
  message: { type: Object, required: true },
  pending: { type: Boolean, default: false }
})
</script>

<template>
  <div class="message-row" :class="message.role">
    <span v-if="message.role === 'assistant'" class="bot-avatar"><Bot :size="17" /></span>
    <div class="message-body">
      <div v-if="message.role === 'assistant'" class="message-meta">AI 咨询助手</div>
      <div class="message-bubble">
        <span v-if="pending && !message.content" class="typing-dots" aria-label="AI 正在思考">
          <i></i>
          <i></i>
          <i></i>
        </span>
        <template v-else>{{ message.content }}</template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.message-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;
}

.message-row.user {
  justify-content: flex-end;
}

.bot-avatar {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--color-primary);
  color: #fff;
}

.message-body {
  max-width: min(72%, 620px);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.message-meta {
  font-size: 12px;
  color: var(--color-text-secondary);
}

.message-bubble {
  padding: 10px 14px;
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.assistant .message-bubble {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
}

.user .message-bubble {
  background: var(--color-primary-soft);
  border: 1px solid #e6c2c7;
}

.typing-dots {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  min-height: 20px;
}

.typing-dots i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: #c79aa0;
  animation: blink 1.2s infinite ease-in-out;
}

.typing-dots i:nth-child(2) {
  animation-delay: 0.15s;
}

.typing-dots i:nth-child(3) {
  animation-delay: 0.3s;
}

@keyframes blink {
  0%,
  80%,
  100% {
    opacity: 0.25;
    transform: translateY(0);
  }
  40% {
    opacity: 1;
    transform: translateY(-3px);
  }
}
</style>
