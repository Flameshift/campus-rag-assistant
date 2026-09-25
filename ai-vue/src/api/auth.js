// 用户鉴权客户端：token 本地存储 + 登录/注册接口封装。

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'
const TOKEN_KEY = 'ai_rag_token'
const USER_KEY = 'ai_rag_user'
export const AUTH_EXPIRED_EVENT = 'ai-auth-expired'

export function getAuthToken() {
  return localStorage.getItem(TOKEN_KEY)
}

export function getStoredUser() {
  try {
    return JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  } catch {
    return null
  }
}

export function setAuth(token, user) {
  localStorage.setItem(TOKEN_KEY, token)
  localStorage.setItem(USER_KEY, JSON.stringify(user))
}

export function clearAuth() {
  localStorage.removeItem(TOKEN_KEY)
  localStorage.removeItem(USER_KEY)
}

/** 通知页面当前登录已失效，由 ChatView 等页面切换到游客模式。 */
export function notifyAuthExpired() {
  window.dispatchEvent(new Event(AUTH_EXPIRED_EVENT))
}

async function authRequest(path, { method = 'POST', body } = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined
  })
  // 204 No Content：登出成功等场景没有响应体。
  if (response.status === 204) return null
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    if (response.status === 401) {
      clearAuth()
      notifyAuthExpired()
    }
    throw new Error(payload.msg || payload.detail || '鉴权请求失败')
  }
  // 后端统一 Result 结构：code=200 表示成功，业务数据放在 data。
  if (payload && typeof payload === 'object' && 'code' in payload) {
    if (String(payload.code) !== '200') {
      throw new Error(payload.msg || '鉴权请求失败')
    }
    return payload.data
  }
  return payload
}

export async function registerUser({ username, password }) {
  return authRequest('/api/auth/register', { body: { username, password } })
}

export async function loginUser({ username, password }) {
  return authRequest('/api/auth/login', { body: { username, password } })
}

export async function logoutRequest() {
  const token = getAuthToken()
  if (!token) return
  return authRequest('/api/auth/logout', { method: 'DELETE' })
}

// TODO: 后端返回结构按 { token, user } 约定对接；登录态接入后可增加用户信息刷新。
