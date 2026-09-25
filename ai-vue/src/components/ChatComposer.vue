<script setup>
import { computed, nextTick, ref, watch } from 'vue'
import { ArrowUp, Paperclip, Square } from '@lucide/vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  busy: { type: Boolean, default: false },
  allowAttach: { type: Boolean, default: true }
})

const emit = defineEmits([
  'update:modelValue',
  'send',
  'stop',
  'attach',
])

const textareaRef = ref(null)
const focused = ref(false)

const canSend = computed(() => props.modelValue.trim().length > 0 && !props.busy)

watch(
  () => props.modelValue,
  async () => {
    await nextTick()
    const element = textareaRef.value
    if (!element) return
    element.style.height = 'auto'
    element.style.height = `${Math.min(element.scrollHeight, 180)}px`
  }
)

function handleSend() {
  if (!canSend.value) return
  emit('send')
  nextTick(() => textareaRef.value?.focus())
}
</script>

<template>
  <div class="composer-wrap">
    <div class="composer" :class="{ 'is-focused': focused }">
      <textarea
        ref="textareaRef"
        :value="modelValue"
        rows="1"
        placeholder="输入校园问题，例如：挂科后如何重修？"
        @input="emit('update:modelValue', $event.target.value)"
        @keydown.enter.exact.prevent="handleSend"
        @focus="focused = true"
        @blur="focused = false"
      ></textarea>
      <div class="composer-tools">
        <div class="tool-left">
          <button v-if="allowAttach" type="button" class="tool-btn" title="上传附件" @click="emit('attach')"><Paperclip :size="18" /></button>
        </div>
        <div class="tool-right">
          <button v-if="busy" type="button" class="stop-btn" title="停止生成" @click="emit('stop')">
            <Square :size="14" :fill="'currentColor'" />
          </button>
          <button v-else type="button" class="send-btn" :disabled="!canSend" title="发送" @click="handleSend">
            <ArrowUp :size="19" />
          </button>
        </div>
      </div>
    </div>
    <p class="composer-hint">回答依据校园知识库，具体以学校正式文件为准</p>
  </div>
</template>

<style scoped>
.composer-wrap {
  flex: 0 0 auto;
  width: 100%;
  max-width: 840px;
  margin: 0 auto;
  padding: 8px 20px 12px;
}

.composer {
  background: var(--color-surface);
  border: 1px solid var(--color-border-strong);
  border-radius: 12px;
  padding: 10px 12px 8px;
  box-shadow: var(--shadow-composer);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.composer.is-focused {
  border-color: var(--color-primary);
  box-shadow: 0 0 0 3px rgba(161, 29, 46, 0.1), var(--shadow-composer);
}

textarea {
  display: block;
  width: 100%;
  min-height: 26px;
  max-height: 180px;
  line-height: 1.6;
  padding: 2px 4px 8px;
}

textarea:focus,
textarea:focus-visible {
  outline: none;
  box-shadow: none;
}

.composer-tools {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}

.tool-left {
  display: flex;
  gap: 2px;
}

.tool-right {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
  flex-wrap: wrap;
}

.tool-btn {
  display: flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: var(--color-text-secondary);
}

.tool-btn:hover {
  background: var(--color-border);
  color: var(--color-text);
}

.send-btn {
  display: flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: var(--color-primary);
  color: #fff;
  transition: background 0.15s ease, opacity 0.15s ease;
}

.send-btn:hover:not(:disabled) {
  background: var(--color-primary-hover);
}

.send-btn:disabled {
  background: #d9c7ca;
  cursor: not-allowed;
}

.stop-btn {
  display: flex;
  width: 36px;
  height: 36px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #b81f30;
  color: #ffffff;
  transition: background 0.15s ease;
}

.stop-btn:hover {
  background: #801724;
}

.composer-hint {
  margin-top: 8px;
  text-align: center;
  font-size: 12px;
  color: var(--color-text-muted);
}

@media (max-width: 767px) {
  .composer-wrap {
    padding: 8px 10px 10px;
  }

}
</style>
