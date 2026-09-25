<script setup>
import { computed, ref } from 'vue'
import {
  CircleHelp,
  Clock3,
  Database,
  LogIn,
  LogOut,
  MessageSquare,
  PanelLeftClose,
  Plus,
  Search,
  Settings,
  Sparkles,
  Trash2,
  UserRound,
  X
} from '@lucide/vue'

const props = defineProps({
  open: { type: Boolean, default: true },
  mobileOpen: { type: Boolean, default: false },
  conversations: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  userName: { type: String, default: '游客' },
  userMode: { type: String, default: '游客模式 · 不保存' },
  loggedIn: { type: Boolean, default: false },
  canManageDocuments: { type: Boolean, default: false }
})

const emit = defineEmits(['toggle', 'new-chat', 'documents', 'select', 'delete', 'close-mobile', 'login', 'logout', 'todo'])

const searchQuery = ref('')

const filteredConversations = computed(() => {
  const query = searchQuery.value.trim().toLowerCase()
  if (!query) return props.conversations
  return props.conversations.filter((conversation) => conversation.title.toLowerCase().includes(query))
})
</script>

<template>
  <aside class="sidebar" :class="{ 'is-closed': !open, 'is-mobile-open': mobileOpen }">
    <div class="sidebar-inner">
      <div class="sidebar-header">
        <button class="brand" title="新建对话" @click="emit('new-chat')">
          <span class="brand-mark"><Sparkles :size="18" /></span>
          <span class="brand-name">校园 AI 咨询</span>
        </button>
        <button class="sidebar-icon collapse-btn" title="收起侧边栏" @click="emit('toggle')"><PanelLeftClose :size="18" /></button>
        <button class="sidebar-icon mobile-close" title="关闭侧边栏" @click="emit('close-mobile')"><X :size="18" /></button>
      </div>
      <button class="new-chat-btn" @click="emit('new-chat')"><Plus :size="16" />新建咨询</button>
      <label class="search-box">
        <Search :size="15" />
        <input v-model="searchQuery" type="search" placeholder="搜索咨询记录" />
      </label>
      <button v-if="canManageDocuments" class="knowledge-entry" @click="emit('documents')">
        <Database :size="16" />
        <span>知识库文档</span>
      </button>
      <div class="history-head">
        <span>咨询记录</span>
        <Clock3 :size="14" />
      </div>
      <nav class="history-list">
        <button
          v-for="conversation in filteredConversations"
          :key="conversation.id"
          class="history-item"
          :class="{ active: conversation.id === activeId }"
          @click="emit('select', conversation.id)"
        >
          <MessageSquare :size="16" class="history-icon" />
          <span class="history-title">{{ conversation.title }}</span>
          <span class="history-delete" title="删除对话" @click.stop="emit('delete', conversation.id)"><Trash2 :size="14" /></span>
        </button>
        <p v-if="filteredConversations.length === 0" class="history-empty">
          {{ searchQuery ? '没有匹配的咨询记录' : '暂无咨询记录，点击上方新建咨询' }}
        </p>
      </nav>
      <div class="sidebar-footer">
        <div class="user-card">
          <span class="user-avatar"><UserRound :size="18" /></span>
          <div class="user-meta">
            <strong>{{ userName }}</strong>
            <span>{{ userMode }}</span>
          </div>
        </div>
        <div class="footer-actions">
          <button class="sidebar-icon" title="设置" @click="emit('todo')"><Settings :size="17" /></button>
          <button class="sidebar-icon" title="帮助" @click="emit('todo')"><CircleHelp :size="17" /></button>
          <button
            v-if="loggedIn"
            class="sidebar-icon"
            title="退出登录"
            @click="emit('logout')"
          >
            <LogOut :size="17" />
          </button>
          <button v-else class="sidebar-icon" title="登录" @click="emit('login')">
            <LogIn :size="17" />
          </button>
        </div>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  flex: 0 0 auto;
  width: var(--sidebar-width);
  height: 100%;
  background: var(--color-surface);
  border-right: 1px solid var(--color-border);
  overflow: hidden;
  transition: width 0.2s ease;
}

.sidebar-inner {
  display: flex;
  flex-direction: column;
  width: var(--sidebar-width);
  height: 100%;
  padding: 12px 10px;
  gap: 10px;
}

.sidebar.is-closed {
  width: 0;
  border-right-color: transparent;
}

.sidebar.is-closed .sidebar-inner {
  opacity: 0;
  pointer-events: none;
}

.sidebar-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 2px;
}

.brand {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 4px 2px;
  text-align: left;
}

.brand-mark {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 9px;
  background: var(--color-primary);
  color: #fff;
}

.brand-name {
  font-size: 15px;
  font-weight: 700;
  white-space: nowrap;
}

.sidebar-icon {
  display: flex;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: var(--color-text-secondary);
}

.sidebar-icon:hover {
  background: var(--color-border);
  color: var(--color-text);
}

.mobile-close {
  display: none;
}

.new-chat-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 38px;
  border-radius: 8px;
  background: var(--color-primary);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}

.new-chat-btn:hover {
  background: var(--color-primary-hover);
}

.search-box {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  color: var(--color-text-muted);
  background: #fff;
}

.search-box:focus-within {
  border-color: var(--color-primary);
}

.search-box input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
}

.knowledge-entry {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 38px;
  padding: 0 10px;
  border: 1px solid var(--color-border);
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
  text-align: left;
}

.knowledge-entry:hover {
  background: var(--color-primary-soft);
  border-color: #dce2ff;
  color: var(--color-primary);
}

.history-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 2px 6px 0;
  font-size: 12px;
  color: var(--color-text-muted);
}

.history-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 2px;
}

.history-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 9px 8px;
  border-radius: 8px;
  color: var(--color-text-secondary);
  font-size: 13px;
  text-align: left;
}

.history-item:hover {
  background: #fff5f6;
  color: var(--color-text);
}

.history-item.active {
  background: var(--color-primary-soft);
  color: var(--color-primary);
  font-weight: 600;
}

.history-icon {
  flex: 0 0 auto;
}

.history-title {
  flex: 1;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.history-delete {
  display: none;
  flex: 0 0 auto;
  padding: 3px;
  border-radius: 6px;
  color: var(--color-text-muted);
}

.history-item:hover .history-delete {
  display: flex;
}

.history-delete:hover {
  background: #f6e4e6;
  color: var(--color-danger);
}

.history-empty {
  padding: 14px 8px;
  font-size: 12px;
  color: var(--color-text-muted);
  line-height: 1.6;
}

.sidebar-footer {
  border-top: 1px solid var(--color-border);
  padding: 10px 2px 2px;
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-card {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
  padding: 4px 2px;
}

.user-avatar {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f3e3e5;
  color: var(--color-primary);
}

.user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.user-meta strong {
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.user-meta span {
  font-size: 11px;
  color: var(--color-text-muted);
  white-space: nowrap;
}

.footer-actions {
  display: flex;
  gap: 2px;
}

@media (max-width: 767px) {
  .sidebar {
    position: fixed;
    inset: 0 auto 0 0;
    z-index: 30;
    transform: translateX(-100%);
    box-shadow: 0 0 0 rgba(0, 0, 0, 0);
    transition: transform 0.2s ease;
  }

  .sidebar.is-mobile-open {
    transform: translateX(0);
    box-shadow: 12px 0 32px rgba(17, 20, 26, 0.18);
  }

  .sidebar.is-closed {
    width: var(--sidebar-width);
    border-right: 1px solid var(--color-border);
  }

  .sidebar.is-closed .sidebar-inner {
    opacity: 1;
    pointer-events: auto;
  }

  .mobile-close {
    display: flex;
  }

  .collapse-btn {
    display: none;
  }
}
</style>
