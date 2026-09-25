<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { CircleHelp, Database, Menu, Search, Settings, Sparkles, UserRound } from '@lucide/vue'
import { deleteShortTermMemory, sendChatMessage, streamChatMessage } from '../api/chat'
import { createConversation, listConversations, removeConversation } from '../api/conversations'
import { AUTH_EXPIRED_EVENT, clearAuth, getAuthToken, getStoredUser, logoutRequest } from '../api/auth'
import AppSidebar from '../components/AppSidebar.vue'
import ChatComposer from '../components/ChatComposer.vue'
import MessageBubble from '../components/MessageBubble.vue'
import WelcomeView from '../components/WelcomeView.vue'

const conversations = ref([
  {
    id: 'c1',
    title: '本科生最长修业年限',
    persisted: false,
    messages: [
      { id: 'm1', role: 'user', content: '本科生最长修业年限一般不超过几年？' },
      {
        id: 'm2',
        role: 'assistant',
        content: '本科在校修读年限一般为四年，最长修业年限一般不超过六年，休学时间计入在校修读年限。'
      }
    ]
  },
  {
    id: 'c2',
    title: '专业必修课挂科处理',
    persisted: false,
    messages: [
      { id: 'm3', role: 'user', content: '专业必修课挂科后应该重修还是补考？' },
      {
        id: 'm4',
        role: 'assistant',
        content: '专业必修课考核不及格必须重修；公共必修课考核不及格一般实行补考。重修需要学生本人提出申请。'
      }
    ]
  },
  {
    id: 'c3',
    title: '宿舍违规电器范围',
    persisted: false,
    messages: [
      { id: 'm5', role: 'user', content: '学生宿舍可以使用哪些电器？' },
      {
        id: 'm6',
        role: 'assistant',
        content: '宿舍严禁使用规定功率以上的大功率违章电器，以及热得快、电热杯、电热水壶、电炉、电磁炉等不符合安全要求的电器。'
      }
    ]
  }
])

// 游客初始状态快照：退出登录或刷新后恢复为纯内存会话。
const guestSnapshot = JSON.parse(JSON.stringify(conversations.value))
const activeConversationId = ref('c1')
const router = useRouter()
const route = useRoute()
const authUser = ref(getStoredUser())
const isLoggedIn = computed(() => Boolean(getAuthToken() && authUser.value))
const isAdmin = computed(() => authUser.value?.role === 'ADMIN')
const draft = ref('')
const typingId = ref(null)
const pendingAssistantId = ref(null)
const sidebarOpen = ref(true)
const mobileNavOpen = ref(false)
const toast = ref('')
const scrollRef = ref(null)
let toastTimer = null
let activeStreamController = null

const activeConversation = computed(() => {
  return (
    conversations.value.find((conversation) => conversation.id === activeConversationId.value) ??
    conversations.value[0] ??
    { id: 'empty', title: '新对话', messages: [] }
  )
})
const isWelcome = computed(() => activeConversation.value.messages.length === 0)
const isTyping = computed(() => typingId.value === activeConversationId.value)

function scrollToBottom() {
  nextTick(() => {
    const element = scrollRef.value
    if (element) element.scrollTop = element.scrollHeight
  })
}

async function startNewChat() {
  let conversation = { id: `c${Date.now()}`, title: '新咨询', messages: [], persisted: false }
  if (isLoggedIn.value) {
    try {
      const created = await createConversation({ title: '新咨询' })
      conversation = { id: created.id, title: created.title, messages: [], persisted: true }
    } catch {
      // TODO: 后端不可用时降级为本地会话，恢复服务后补同步。
    }
  }
  conversations.value.unshift(conversation)
  activeConversationId.value = conversation.id
  draft.value = ''
  typingId.value = null
  mobileNavOpen.value = false
  scrollToBottom()
}

async function loadConversations() {
  if (!isLoggedIn.value) return
  try {
    const data = await listConversations()
    const items = Array.isArray(data) ? data : (data.conversations || [])
    const serverConversations = items.map((item) => ({
      id: item.id,
      title: item.title || '新对话',
      messages: (item.messages || []).map((message) => ({
        id: message.id,
        role: message.role,
        content: message.content
      })),
      persisted: true
    }))

    if (serverConversations.length > 0) {
      conversations.value = serverConversations
      activeConversationId.value = serverConversations[0].id
    } else {
      conversations.value = []
      await startNewChat()
    }
  } catch {
    // TODO: 后端恢复后自动重试同步本地会话。
    showToast('会话服务不可用，已切换为游客模式')
  }
}

onMounted(async () => {
  if (isLoggedIn.value) await loadConversations()
  const initialQuestion = String(route.query.q || '').trim()
  if (initialQuestion) {
    await startNewChat()
    await nextTick()
    sendMessage(initialQuestion)
    router.replace({ path: '/chat' })
  }
  window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
})

onBeforeUnmount(() => {
  window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired)
})

function selectConversation(id) {
  activeConversationId.value = id
  mobileNavOpen.value = false
  scrollToBottom()
}

function toggleNavigation() {
  if (window.innerWidth <= 767) {
    mobileNavOpen.value = !mobileNavOpen.value
    return
  }
  sidebarOpen.value = !sidebarOpen.value
}

async function deleteConversation(id) {
  const conversation = conversations.value.find((item) => item.id === id)
  const index = conversations.value.findIndex((conversation) => conversation.id === id)
  if (index === -1) return
  conversations.value.splice(index, 1)
  try {
    await deleteShortTermMemory(id)
  } catch {
    // 短期记忆有 TTL，删除失败不会阻塞会话删除。
  }
  if (conversation?.persisted) {
    try {
      await removeConversation(id)
    } catch {
      // TODO: 删除失败时本地标记待同步。
    }
  }
  if (typingId.value === id) typingId.value = null
  if (conversations.value.length === 0) {
    startNewChat()
    return
  }
  if (activeConversationId.value === id) {
    activeConversationId.value = conversations.value[Math.min(index, conversations.value.length - 1)].id
  }
}

async function sendMessage(text) {
  const content = (text ?? draft.value).trim()
  if (!content || isTyping.value) return
  const conversation = activeConversation.value
  conversation.messages.push({ id: `m${Date.now()}`, role: 'user', content })
  if (conversation.title === '新咨询') {
    conversation.title = content.length > 16 ? `${content.slice(0, 16)}…` : content
  }
  draft.value = ''
  typingId.value = conversation.id
  scrollToBottom()

  // 传给后端的对话上下文：去掉刚发送的这条问题，避免重复。
  const history = conversation.messages
    .slice(0, -1)
    .map((message) => ({ role: message.role, content: message.content }))

  // 先创建空的 assistant 消息，流式生成时逐字填充。
  const assistantId = `m${Date.now()}-r`
  conversation.messages.push({ id: assistantId, role: 'assistant', content: '' })
  pendingAssistantId.value = assistantId
  const assistantMessage = conversation.messages.find((message) => message.id === assistantId)
  scrollToBottom()

  // 创建本次流式请求的控制器，停止按钮通过它中断生成。
  const controller = new AbortController()
  activeStreamController = controller
  let stoppedByUser = false

  try {
    await streamChatMessage({
      question: content,
      history,
      conversationId: conversation.id,
      signal: controller.signal,
      onToken: (token) => {
        assistantMessage.content += token
        scrollToBottom()
      },
      onReplace: (content) => {
        assistantMessage.content = content
        scrollToBottom()
      }
    })
  } catch (err) {
    stoppedByUser = err?.name === 'AbortError' || controller.signal.aborted
    if (!stoppedByUser) {
      // 流式失败：清空部分内容，改用普通接口兜底。
      assistantMessage.content = ''
      try {
        const data = await sendChatMessage({
          question: content,
          history,
          conversationId: conversation.id
        })
        assistantMessage.content = data.answer
      } catch {
        // TODO: 接入正式错误码与重试机制后，移除模拟回复兜底。
        assistantMessage.content = buildReply(content)
        showToast('后端暂不可用，已使用模拟回复')
      }
    }
  } finally {
    if (activeStreamController === controller) activeStreamController = null
    if (pendingAssistantId.value === assistantId) pendingAssistantId.value = null
  }

  const stillExists = conversations.value.some((item) => item.id === conversation.id)
  if (!stillExists || typingId.value !== conversation.id) return
  const reply = assistantMessage.content
  const replyEmpty = !reply.trim()
  typingId.value = null
  scrollToBottom()

  // 用户停止且没有任何生成内容时，不保留空的助手气泡。
  if (replyEmpty) {
    const messageIndex = conversation.messages.findIndex((message) => message.id === assistantId)
    if (messageIndex !== -1) conversation.messages.splice(messageIndex, 1)
  }

}

function stopGeneration() {
  if (activeStreamController) {
    activeStreamController.abort()
    activeStreamController = null
  }
}

function buildReply(question) {
  return `已收到你的校园问题：「${question}」。\n\n当前后端暂不可用，未返回知识库结果。请稍后重试，系统会按学生手册和相关制度给出有来源的回答。`
}

function handleSuggestion(prompt) {
  sendMessage(prompt)
}

function resetToGuest() {
  conversations.value = JSON.parse(JSON.stringify(guestSnapshot))
  activeConversationId.value = conversations.value[0]?.id
  authUser.value = null
  typingId.value = null
  draft.value = ''
}

async function handleLogout() {
  try {
    await logoutRequest()
  } catch {
    // 后端登出失败也清除本地登录态。
  }
  clearAuth()
  resetToGuest()
  showToast('已退出登录，当前为游客模式')
}

function handleAuthExpired() {
  resetToGuest()
  showToast('登录已过期，请重新登录')
  router.push('/auth')
}

function goToAuth() {
  router.push('/auth')
}

function showToast(message) {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2200)
}

function goToUpload() {
  router.push('/upload')
}
</script>

<template>
  <div class="app-shell">
    <AppSidebar
      :open="sidebarOpen"
      :mobile-open="mobileNavOpen"
      :conversations="conversations"
      :active-id="activeConversationId"
      :user-name="authUser?.username || '游客'"
      :user-mode="isLoggedIn ? '校园事务咨询' : '游客模式 · 不保存'"
      :logged-in="isLoggedIn"
      :can-manage-documents="isAdmin"
      @new-chat="startNewChat"
      @documents="router.push('/documents')"
      @select="selectConversation"
      @delete="deleteConversation"
      @toggle="sidebarOpen = !sidebarOpen"
      @close-mobile="mobileNavOpen = false"
      @login="goToAuth"
      @logout="handleLogout"
      @todo="showToast('该功能待接入')"
    />
    <div v-if="mobileNavOpen" class="mobile-mask" @click="mobileNavOpen = false"></div>
    <main class="chat-main">
      <header class="topbar">
        <button
          class="topbar-icon menu-btn"
          :class="{ 'is-sidebar-closed': !sidebarOpen }"
          :title="sidebarOpen ? '收起侧边栏' : '展开侧边栏'"
          @click="toggleNavigation"
        >
          <Menu :size="20" />
        </button>
        <div class="topbar-title">
          <span class="topbar-badge"><Sparkles :size="14" /></span>
        <span class="topbar-text">{{ isWelcome ? '校园事务咨询' : activeConversation.title }}</span>
        </div>
        <div class="topbar-actions">
          <button v-if="isAdmin" class="topbar-icon" title="知识库文档" @click="router.push('/documents')"><Database :size="19" /></button>
          <button class="topbar-icon" title="搜索" @click="showToast('搜索功能待接入')"><Search :size="19" /></button>
          <button class="topbar-icon" title="设置" @click="showToast('设置功能待接入')"><Settings :size="19" /></button>
          <button class="topbar-icon" title="帮助" @click="showToast('帮助中心待接入')"><CircleHelp :size="19" /></button>
          <button
            class="avatar-btn"
            :title="isLoggedIn ? '退出登录' : '登录'"
            @click="isLoggedIn ? handleLogout() : goToAuth()"
          >
            <UserRound :size="17" />
          </button>
        </div>
      </header>
      <div ref="scrollRef" class="chat-scroll">
        <WelcomeView v-if="isWelcome" @pick="handleSuggestion" />
        <div v-else class="message-list">
          <MessageBubble
            v-for="message in activeConversation.messages"
            :key="message.id"
            :message="message"
            :pending="message.id === pendingAssistantId"
          />
        </div>
      </div>
      <ChatComposer
        v-model="draft"
        :busy="isTyping"
        :allow-attach="isAdmin"
        @stop="stopGeneration"
        @attach="goToUpload"
        @send="sendMessage"
      />
    </main>
    <transition name="toast">
      <div v-if="toast" class="toast">{{ toast }}</div>
    </transition>
  </div>
</template>

<style scoped>
.app-shell {
  --color-bg: #fffafa;
  --color-surface: #ffffff;
  --color-border: #f0d5d8;
  --color-border-strong: #e6c2c7;
  --color-text: #38292c;
  --color-text-secondary: #8a6d72;
  --color-text-muted: #b08a90;
  --color-primary: #a11d2e;
  --color-primary-hover: #86182a;
  --color-primary-soft: #fbecee;
  --color-danger: #c0392b;
  --shadow-composer: 0 8px 28px rgba(120, 20, 32, 0.08);
  display: flex;
  height: 100dvh;
  min-height: 100vh;
  overflow: hidden;
  background: var(--color-bg);
}

.mobile-mask {
  display: none;
}

.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  position: relative;
}

.topbar {
  flex: 0 0 auto;
  height: var(--topbar-height);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 0 16px;
  background: rgba(255, 255, 255, 0.94);
  border-bottom: 1px solid var(--color-border);
  backdrop-filter: blur(12px);
}

.topbar-title {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  min-width: 0;
}

.topbar-badge {
  display: flex;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.topbar-text {
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.topbar-actions {
  display: flex;
  align-items: center;
  gap: 2px;
}

.topbar-icon {
  display: flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: var(--color-text-secondary);
}

.topbar-icon:hover {
  background: var(--color-border);
  color: var(--color-text);
}

.avatar-btn {
  display: flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 50%;
  background: #f3e3e5;
  color: var(--color-text-secondary);
  margin-left: 6px;
}

.menu-btn {
  display: none;
}

.menu-btn.is-sidebar-closed {
  display: flex;
}

.chat-scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  background: var(--color-bg);
}

.message-list {
  width: 100%;
  max-width: 820px;
  margin: 0 auto;
  padding: 20px 20px 28px;
  display: flex;
  flex-direction: column;
  gap: 22px;
  flex: 1;
}

.toast {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 60;
  background: #20242c;
  color: #fff;
  padding: 9px 16px;
  border-radius: 8px;
  font-size: 13px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.18);
}

.toast-enter-active,
.toast-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translate(-50%, -8px);
}

@media (max-width: 767px) {
  .menu-btn {
    display: flex;
  }

  .topbar {
    padding: 0 10px;
  }

  .mobile-mask {
    display: block;
    position: fixed;
    inset: 0;
    z-index: 20;
    background: rgba(52, 22, 27, 0.32);
  }

  .message-list {
    padding: 14px 14px 20px;
    gap: 18px;
  }
}
</style>
