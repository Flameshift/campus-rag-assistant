// 前端 API 客户端：统一封装对 ai-rag 后端的调用。

import { getAuthToken } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'

function requestHeaders() {
  const token = getAuthToken()
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  }
}

/**
 * 发送问答请求。
 * 返回 { answer, sources, mode }；后端不可用时抛出异常，由调用方降级处理。
 */
export async function sendChatMessage({ question, history = [], conversationId }) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 600000)

  try {
    const response = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      headers: requestHeaders(),
      credentials: 'include',
      body: JSON.stringify({ question, history, conversation_id: conversationId }),
      signal: controller.signal
    })
    const data = await response.json()
    if (!response.ok) {
      throw new Error(typeof data.detail === 'string' ? data.detail : '服务返回异常')
    }
    return data
  } finally {
    window.clearTimeout(timer)
  }
}

/**
 * 流式问答请求（SSE）。
 * 成功后逐段调用 onToken / onSources；任何失败都会抛出异常，由调用方降级处理。
 */
export async function streamChatMessage({
  question,
  history = [],
  conversationId,
  onToken,
  onSources,
  onReplace,
  signal
}) {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 600000)
  const onOuterAbort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', onOuterAbort, { once: true })

  try {
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: requestHeaders(),
      credentials: 'include',
      body: JSON.stringify({ question, history, conversation_id: conversationId }),
      signal: controller.signal
    })
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}))
      throw new Error(typeof data.detail === 'string' ? data.detail : '流式接口不可用')
    }

    const reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let serverError = null

    while (true) {
      const { value, done } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const raw of lines) {
        const line = raw.trim()
        if (!line.startsWith('data:')) continue
        const payload = line.slice(5).trim()
        if (!payload) continue

        let event
        try {
          event = JSON.parse(payload)
        } catch {
          continue
        }

        if (event.type === 'token' && typeof onToken === 'function') {
          onToken(event.content || '')
        } else if (event.type === 'replace' && typeof onReplace === 'function') {
          onReplace(event.content || '')
        } else if (event.type === 'sources' && typeof onSources === 'function') {
          onSources(event.sources || [])
        } else if (event.type === 'error') {
          serverError = event.message || '流式生成失败'
          break
        }
      }
      if (serverError) break
    }

    if (serverError) throw new Error(serverError)
    return { ok: true }
  } finally {
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', onOuterAbort)
  }
}

export async function deleteShortTermMemory(conversationId) {
  if (!conversationId) return null
  const query = `?conversation_id=${encodeURIComponent(conversationId)}`
  const response = await fetch(`${API_BASE}/api/memory${query}`, {
    method: 'DELETE',
    headers: requestHeaders(),
    credentials: 'include'
  })
  if (!response.ok) return null
  return response.json().catch(() => null)
}

// TODO: 补充请求重试、错误码分类与统一上报。
