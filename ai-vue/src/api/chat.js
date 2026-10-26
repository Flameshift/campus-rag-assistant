// 前端 API 客户端：统一封装普通问答、SSE 流式问答和短期记忆接口。
// 所有请求默认经过 Spring Boot 网关，浏览器不直接访问 Python RAG 服务。

import { getAuthToken } from './auth'

// 默认使用本地 Spring Boot 网关；部署时可通过 VITE_API_BASE_URL 覆盖。
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'
const STREAM_TIMEOUT_MS = 600000

/**
 * 构造请求头。
 *
 * 登录用户自动携带 Bearer Token；游客不携带 Authorization，
 * 由 Spring Boot 根据签名 Cookie 识别游客会话。
 */
function requestHeaders() {
  const token = getAuthToken()
  return {
    'Content-Type': 'application/json',
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  }
}

/**
 * 普通问答请求，调用 Spring Boot 的 /api/chat。
 *
 * 特点：
 * - 非流式，等待完整回答后一次性返回；
 * - 适合流式接口失败后的降级调用；
 * - 返回 { answer, sources, mode, timings, confidence }；
 * - 后端异常时抛出 Error，由调用方决定是否显示本地兜底内容。
 */
export async function sendChatMessage({ question, history = [], conversationId }) {
  // 超时保护：即使后端服务卡住，也会在 10 分钟后主动中断请求。
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), 600000)

  try {
    // credentials='include' 让浏览器携带 Spring Boot 的游客签名 Cookie。
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
 * 流式问答请求，调用 Spring Boot 的 /api/chat/stream。
 *
 * SSE 事件解析策略：
 * - 按空行划分一个完整 SSE 事件，同一事件允许多条 data: 行；
 * - 每次 reader.read() 可能得到半条或多条事件，因此用 buffer 暂存未完成行；
 * - data: 行按 SSE 规范用换行拼接后，再交给 JSON.parse；
 * - token 用于追加增量文本；
 * - replace 用于回答复核后整体替换；
 * - sources 用于更新引用来源；
 * - error 会记录服务端错误，循环结束后抛出，由调用方降级到普通接口。
 *
 * signal 是外层页面的取消信号，例如 ChatView 的停止生成按钮。
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
  let reader = null

  // 同时支持“内部超时”和“外部用户停止”两套取消来源。
  // 保留手动组合而不强依赖 AbortSignal.any，以兼容尚未支持该 API 的浏览器。
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort(), STREAM_TIMEOUT_MS)
  const onOuterAbort = () => controller.abort()
  if (signal?.aborted) controller.abort()
  else signal?.addEventListener('abort', onOuterAbort, { once: true })

  try {
    // 浏览器保持连接，Spring Boot 再将 Python 的 SSE 字节流逐块转发到这里。
    const response = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      headers: requestHeaders(),
      credentials: 'include',
      body: JSON.stringify({ question, history, conversation_id: conversationId }),
      signal: controller.signal
    })

    // 非 2xx 或浏览器没有可读流时，直接交给调用方执行普通接口兜底。
    if (!response.ok || !response.body) {
      const data = await response.json().catch(() => ({}))
      throw new Error(typeof data.detail === 'string' ? data.detail : '流式接口不可用')
    }

    // 使用 Web Streams 读取 SSE；TextDecoder 保持 UTF-8 跨块解码。
    reader = response.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buffer = ''
    let dataLines = []
    let serverError = null

    // 回调属于渲染层，不能因为 UI 更新异常中断网络读取。
    // 同步异常直接记录；异步回调产生的 rejected Promise 也不会形成未处理异常。
    const invokeCallback = (name, callback, ...args) => {
      if (typeof callback !== 'function') return
      try {
        const result = callback(...args)
        if (result && typeof result.then === 'function') {
          result.catch((error) => console.error(`[streamChatMessage] ${name} 回调执行失败`, error))
        }
      } catch (error) {
        console.error(`[streamChatMessage] ${name} 回调执行失败`, error)
      }
    }

    // 处理一个完整 SSE 事件的 data 内容。
    const dispatchEvent = (payload) => {
      if (!payload) return false

      // 后端约定每个事件都是一段 JSON；单条脏数据不应中断后续答案。
      let event
      try {
        event = JSON.parse(payload)
      } catch {
        return false
      }

      // 内容字段做严格类型检查，避免对象或数组被误拼进页面文本。
      if (event?.type === 'token' && typeof onToken === 'function') {
        if (typeof event.content === 'string') invokeCallback('onToken', onToken, event.content)
      } else if (event?.type === 'replace' && typeof onReplace === 'function') {
        if (typeof event.content === 'string') invokeCallback('onReplace', onReplace, event.content)
      } else if (event?.type === 'sources' && typeof onSources === 'function') {
        if (Array.isArray(event.sources)) invokeCallback('onSources', onSources, event.sources)
      } else if (event?.type === 'error') {
        serverError = typeof event.message === 'string' && event.message
          ? event.message
          : '流式生成失败'
        return true
      }
      return false
    }

    // 逐行解析 SSE 字段。空行代表当前事件结束。
    const consumeLine = (rawLine) => {
      // 兼容 CRLF：split('\n') 后普通行的末尾会残留一个 '\r'。
      const line = rawLine.endsWith('\r') ? rawLine.slice(0, -1) : rawLine
      if (!line) {
        if (dataLines.length === 0) return false
        const payload = dataLines.join('\n')
        dataLines = []
        return dispatchEvent(payload)
      }

      // 注释行以及 event/id/retry 等字段不参与当前 JSON 数据协议。
      if (line.startsWith(':')) return false
      const colonIndex = line.indexOf(':')
      const field = colonIndex === -1 ? line : line.slice(0, colonIndex)
      if (field !== 'data') return false

      // 标准 SSE 允许冒号后有一个可选空格，该空格不属于数据内容。
      let value = colonIndex === -1 ? '' : line.slice(colonIndex + 1)
      if (value.startsWith(' ')) value = value.slice(1)
      dataLines.push(value)
      return false
    }

    while (true) {
      const { value, done } = await reader.read()
      if (done) break

      // SSE 事件以换行分隔，但网络分块不等于事件边界，因此必须维持 buffer。
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const raw of lines) {
        if (consumeLine(raw)) {
          break
        }
      }
      if (serverError) break
    }

    // 刷新 TextDecoder 并处理连接结束时没有尾部换行的最后一条事件。
    if (!serverError) {
      buffer += decoder.decode()
      for (const raw of buffer.split('\n')) {
        if (consumeLine(raw)) break
      }
      if (!serverError && dataLines.length > 0) consumeLine('')
    }

    // Python 端明确发送的 error 事件优先于普通网络错误向上抛出。
    if (serverError) throw new Error(serverError)
    return { ok: true }
  } finally {
    // 无论正常结束、用户停止还是回调/网络异常，都释放 reader 并清理取消监听。
    if (reader) {
      try {
        await reader.cancel()
      } catch {
        // 流已经关闭时 cancel() 可能 reject，此处无需向上传递。
      }
    }
    window.clearTimeout(timer)
    signal?.removeEventListener('abort', onOuterAbort)
  }
}

/**
 * 删除指定会话的短期记忆。
 *
 * 登录用户由 Spring Boot 校验 conversation_id 归属，游客使用签名 Cookie
 * 对应的 guest thread_id。删除失败返回 null，不影响前端删除本地会话。
 */
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

// TODO: 后续补充请求重试、错误码分类、请求 ID 透传和统一错误上报。
