// 知识库文档管理 API。

import { getAuthToken } from './auth'

const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'

function headers(json = true) {
  const token = getAuthToken()
  return {
    ...(json ? { 'Content-Type': 'application/json' } : {}),
    ...(token ? { Authorization: `Bearer ${token}` } : {})
  }
}

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      ...headers(!(options.body instanceof FormData)),
      ...(options.headers || {})
    }
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    throw new Error(payload.msg || payload.detail || `请求失败: ${response.status}`)
  }
  return payload?.data ?? payload
}

export function listDocuments() {
  return request('/api/admin/documents')
}

export function listDocumentTasks(documentId = '') {
  const query = documentId ? `?document_id=${encodeURIComponent(documentId)}` : ''
  return request(`/api/admin/tasks${query}`)
}

export function listDocumentVersions(documentId) {
  return request(`/api/admin/documents/${documentId}/versions`)
}

export function activateDocumentVersion(versionId) {
  return request(`/api/admin/documents/${versionId}/activate-version`, {
    method: 'POST'
  })
}

export function reindexDocument(documentId) {
  return request(`/api/admin/documents/${documentId}/reindex`, { method: 'POST' })
}

export function disableDocument(documentId) {
  return request(`/api/admin/documents/${documentId}/disable`, { method: 'POST' })
}

export function restoreDocument(documentId) {
  return request(`/api/admin/documents/${documentId}/restore`, { method: 'POST' })
}

export function deleteDocument(documentId) {
  return request(`/api/admin/documents/${documentId}`, { method: 'DELETE' })
}

export function uploadDocumentVersion(documentId, file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/api/admin/documents/${documentId}/versions`)
    const token = getAuthToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable && typeof onProgress === 'function') {
        onProgress(Math.round((event.loaded / event.total) * 100))
      }
    }

    xhr.onload = () => {
      let payload = {}
      try {
        payload = JSON.parse(xhr.responseText || '{}')
      } catch {
        payload = {}
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(payload?.data ?? payload)
      } else {
        reject(new Error(payload.msg || payload.detail || `上传失败: ${xhr.status}`))
      }
    }
    xhr.onerror = () => reject(new Error('网络错误'))

    const form = new FormData()
    form.append('file', file)
    form.append('upload_id', `version-${documentId}-${Date.now()}`)
    xhr.send(form)
  })
}
