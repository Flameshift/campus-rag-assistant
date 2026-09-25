// 会话历史 API 客户端：登录后通过 Bearer Token 调用后端会话接口。

import { clearAuth, getAuthToken, notifyAuthExpired } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'

async function request(path, options = {}) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 10000)
  const token = getAuthToken()

  try {
    const response = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {})
      },
      signal: controller.signal
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      if (response.status === 401) {
        clearAuth()
        notifyAuthExpired()
      }
      throw new Error(payload.msg || payload.detail || `请求失败: ${response.status}`)
    }
    const payload = await response.json().catch(() => null)
    // 后端统一 Result 结构：成功时返回 data，失败时抛出 msg。
    if (payload && typeof payload === 'object' && 'code' in payload) {
      if (String(payload.code) !== '200') {
        throw new Error(payload.msg || '请求失败')
      }
      return payload.data
    }
    return payload
  } finally {
    window.clearTimeout(timer)
  }
}

export function listConversations() {
  return request('/api/conversations')
}

export function createConversation({ title = '新对话' } = {}) {
  return request('/api/conversations', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ title })
  })
}

export function appendMessage(conversationId, role, content) {
  return request(`/api/conversations/${conversationId}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ role, content })
  })
}

export function removeConversation(conversationId) {
  return request(`/api/conversations/${conversationId}`, {
    method: 'DELETE'
  })
}

// TODO: 后端会话接口完成鉴权后，服务端从 Token 推导用户，前端不再传 user_id。
