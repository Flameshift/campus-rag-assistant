<script setup>
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { getAuthToken } from '../api/auth'
import {
  ArrowLeft,
  CircleAlert,
  CircleCheck,
  CloudUpload,
  Database,
  FileText,
  LoaderCircle,
  Sparkles,
  Trash2,
  X
} from '@lucide/vue'

const router = useRouter()
// 所有请求统一走 Spring Boot 网关。
const API_BASE = import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8080'

const ALLOWED_EXTENSIONS = ['.pdf', '.docx', '.txt', '.md', '.csv', '.json']
const MAX_FILE_SIZE = 50 * 1024 * 1024
// 同时上传的文件数量，避免一次性打满后端与 Python 服务。
const CONCURRENCY = 2

const fileInput = ref(null)
const dragActive = ref(false)
const files = ref([])
const uploading = ref(false)
const error = ref('')
const summary = ref('')

const pendingCount = computed(
  () => files.value.filter((item) => item.status === 'waiting' || item.status === 'failed').length
)
const totalBytes = computed(() => files.value.reduce((sum, item) => sum + item.size, 0))
const loadedBytes = computed(
  () => files.value.reduce((sum, item) => sum + (item.size * item.progress) / 100, 0)
)
const overallProgress = computed(() =>
  totalBytes.value === 0 ? 0 : Math.round((loadedBytes.value / totalBytes.value) * 100)
)

function formatSize(bytes) {
  const kb = bytes / 1024
  return kb > 1024 ? `${(kb / 1024).toFixed(2)} MB` : `${kb.toFixed(1)} KB`
}

function statusText(item) {
  if (item.status === 'waiting') return '等待上传'
  if (item.status === 'uploading') return `上传中 ${item.progress}%`
  if (item.status === 'failed') return '上传失败'
  return '上传完成'
}

/** 把选择/拖入的文件加入列表，逐个做类型与大小校验。 */
function addFiles(fileList) {
  error.value = ''
  summary.value = ''

  for (const file of Array.from(fileList)) {
    const supported = ALLOWED_EXTENSIONS.some((ext) => file.name.toLowerCase().endsWith(ext))
    if (!supported) {
      error.value = `已跳过不支持的文件：${file.name}`
      continue
    }
    if (file.size > MAX_FILE_SIZE) {
      error.value = `文件超过 50MB：${file.name}`
      continue
    }
    files.value.push({
      id: crypto.randomUUID(),
      file,
      name: file.name,
      size: file.size,
      status: 'waiting',
      progress: 0,
      message: '',
      uploadId: crypto.randomUUID()
    })
  }
}

function pickFiles(event) {
  addFiles(event.target.files)
  event.target.value = ''
}

function onDrop(event) {
  dragActive.value = false
  addFiles(event.dataTransfer.files)
}

function removeItem(id) {
  if (uploading.value) return
  files.value = files.value.filter((item) => item.id !== id)
}

function clearAll() {
  if (uploading.value) return
  files.value = []
  error.value = ''
  summary.value = ''
}

/**
 * 单文件上传。
 * 使用 XMLHttpRequest，因为 fetch 无法获取上传进度。
 */
function uploadOne(item) {
  return new Promise((resolve) => {
    item.status = 'uploading'
    item.progress = 0
    item.message = ''

    const xhr = new XMLHttpRequest()
    xhr.open('POST', `${API_BASE}/api/upload`)
    const token = getAuthToken()
    if (token) xhr.setRequestHeader('Authorization', `Bearer ${token}`)

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        item.progress = Math.round((event.loaded / event.total) * 100)
      }
    }

    xhr.onload = () => {
      let data = {}
      try {
        data = JSON.parse(xhr.responseText || '{}')
      } catch {
        data = {}
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        item.progress = 100
        item.status = 'done'
        item.message = data.message || '上传完成'
      } else {
        item.status = 'failed'
        item.message = data.msg || data.detail || `上传失败 (${xhr.status})`
      }
      resolve()
    }

    xhr.onerror = () => {
      item.status = 'failed'
      item.message = '网络错误'
      resolve()
    }

    xhr.onabort = () => {
      item.status = 'failed'
      item.message = '已取消'
      resolve()
    }

    const form = new FormData()
    form.append('file', item.file)
    // 每个文件独立 upload_id，后端据此做幂等与去重。
    form.append('upload_id', item.uploadId)
    xhr.send(form)
  })
}

/** 并发上传：固定两个 worker 从队列取任务。 */
async function uploadAll() {
  if (uploading.value) return
  const queue = files.value.filter((item) => item.status === 'waiting' || item.status === 'failed')
  if (queue.length === 0) return

  uploading.value = true
  error.value = ''
  summary.value = ''
  let cursor = 0

  const workers = Array.from({ length: Math.min(CONCURRENCY, queue.length) }, async () => {
    while (cursor < queue.length) {
      const item = queue[cursor]
      cursor += 1
      await uploadOne(item)
    }
  })

  await Promise.all(workers)
  uploading.value = false

  const done = files.value.filter((item) => item.status === 'done').length
  const failed = files.value.filter((item) => item.status === 'failed').length
  summary.value = `上传结束：成功 ${done} 个，失败 ${failed} 个`
}
</script>

<template>
  <div class="upload-page">
    <header class="upload-nav">
      <button class="back-btn" type="button" @click="router.push('/')">
        <ArrowLeft :size="17" />返回首页
      </button>
      <div class="nav-brand">
        <span class="brand-mark"><Sparkles :size="16" /></span>
        <span>AI 咨询助手</span>
      </div>
      <RouterLink class="nav-chat" to="/chat">开始对话</RouterLink>
      <RouterLink class="nav-documents" to="/documents">管理文档</RouterLink>
    </header>

    <main class="upload-main">
      <div class="upload-panel">
        <div class="page-head">
          <span class="page-icon"><Database :size="22" /></span>
          <div>
            <h1>知识库上传</h1>
            <p>支持多文件批量上传，单文件最大 50MB</p>
          </div>
        </div>

        <div
          class="drop-zone"
          :class="{ active: dragActive }"
          @dragover.prevent="dragActive = true"
          @dragleave.prevent="dragActive = false"
          @drop.prevent="onDrop"
          @click="fileInput?.click()"
        >
          <span class="drop-icon"><CloudUpload :size="26" /></span>
          <strong>选择或拖拽文件</strong>
          <span class="drop-tip">支持多选 · PDF · Word · Markdown · TXT · CSV · JSON</span>
          <input
            ref="fileInput"
            type="file"
            multiple
            accept=".pdf,.docx,.txt,.md,.csv,.json"
            hidden
            @change="pickFiles"
          />
        </div>

        <div v-if="files.length" class="overall">
          <div class="overall-head">
            <span>总进度</span>
            <span>{{ overallProgress }}%</span>
          </div>
          <div class="progress-track">
            <div class="progress-bar" :style="{ width: `${overallProgress}%` }"></div>
          </div>
        </div>

        <ul v-if="files.length" class="file-list">
          <li v-for="item in files" :key="item.id" class="file-item">
            <span class="file-icon"><FileText :size="18" /></span>
            <div class="file-body">
              <div class="file-head">
                <strong>{{ item.name }}</strong>
                <span class="file-size">{{ formatSize(item.size) }}</span>
              </div>
              <div class="progress-track small">
                <div
                  class="progress-bar"
                  :class="{ failed: item.status === 'failed' }"
                  :style="{ width: `${item.progress}%` }"
                ></div>
              </div>
              <div class="file-status" :class="item.status">
                <CircleCheck v-if="item.status === 'done'" :size="14" />
                <CircleAlert v-else-if="item.status === 'failed'" :size="14" />
                <LoaderCircle v-else-if="item.status === 'uploading'" class="spin" :size="14" />
                <span>{{ item.message || statusText(item) }}</span>
              </div>
            </div>
            <button class="remove-btn" type="button" title="移除" @click="removeItem(item.id)">
              <X :size="16" />
            </button>
          </li>
        </ul>

        <div class="actions">
          <button class="upload-btn" type="button" :disabled="pendingCount === 0 || uploading" @click="uploadAll">
            <LoaderCircle v-if="uploading" class="spin" :size="18" />
            <CloudUpload v-else :size="18" />
            {{ uploading ? '正在上传…' : `开始上传${pendingCount ? ` (${pendingCount})` : ''}` }}
          </button>
          <button class="clear-btn" type="button" :disabled="files.length === 0 || uploading" @click="clearAll">
            <Trash2 :size="16" />清空
          </button>
        </div>

        <div v-if="error" class="result-box error">
          <CircleAlert :size="18" />
          <span>{{ error }}</span>
        </div>
        <div v-if="summary" class="result-box success">
          <CircleCheck :size="18" />
          <span>{{ summary }}</span>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.upload-page {
  min-height: 100dvh;
  background: #ffffff;
  color: #38292c;
}

.upload-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 64px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.92);
  border-bottom: 1px solid #f0d5d8;
  backdrop-filter: blur(12px);
}

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px 12px;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 13px;
  font-weight: 600;
}

.back-btn:hover {
  background: #fbecee;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 auto;
  font-size: 15px;
  font-weight: 700;
}

.brand-mark {
  display: inline-flex;
  width: 30px;
  height: 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #a11d2e;
  color: #fff;
}

.nav-chat {
  padding: 8px 14px;
  border-radius: 8px;
  background: #a11d2e;
  color: #fff;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.nav-documents {
  padding: 8px 14px;
  border: 1px solid #e6c2c7;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.nav-documents:hover {
  background: #fbecee;
}

.upload-main {
  display: flex;
  justify-content: center;
  padding: 48px 20px 64px;
}

.upload-panel {
  width: 100%;
  max-width: 760px;
  padding: 34px;
  border: 1px solid #e9ccd1;
  border-radius: 8px;
  background: #fffdfd;
  box-shadow: 0 10px 30px rgba(120, 20, 32, 0.06);
}

.page-head {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 26px;
}

.page-icon {
  display: flex;
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #a11d2e;
}

.page-head h1 {
  font-size: 24px;
  color: #801724;
}

.page-head p {
  margin-top: 4px;
  color: #8a6d72;
  font-size: 13px;
}

.drop-zone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 180px;
  padding: 24px;
  border: 1.5px dashed #d9a7ae;
  border-radius: 8px;
  background: #fdf7f8;
  cursor: pointer;
}

.drop-zone:hover,
.drop-zone.active {
  border-color: #a11d2e;
  background: #fbecee;
}

.drop-icon {
  display: flex;
  width: 52px;
  height: 52px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #a11d2e;
}

.drop-zone strong {
  font-size: 15px;
}

.drop-tip {
  color: #b08a90;
  font-size: 12px;
}

.overall {
  margin-top: 20px;
}

.overall-head {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
  color: #8a6d72;
  font-size: 12px;
}

.progress-track {
  height: 6px;
  border-radius: 999px;
  background: #f4dfe2;
  overflow: hidden;
}

.progress-track.small {
  height: 4px;
}

.progress-bar {
  height: 100%;
  width: 0;
  border-radius: 999px;
  background: #a11d2e;
  transition: width 0.2s ease;
}

.progress-bar.failed {
  background: #d9534f;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 18px;
  list-style: none;
}

.file-item {
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 14px;
  border: 1px solid #e9ccd1;
  border-radius: 8px;
  background: #ffffff;
}

.file-icon {
  display: flex;
  width: 36px;
  height: 36px;
  flex: 0 0 36px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #a11d2e;
}

.file-body {
  flex: 1;
  min-width: 0;
}

.file-head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  margin-bottom: 8px;
  font-size: 13px;
}

.file-head strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.file-size {
  flex: 0 0 auto;
  color: #8a6d72;
  font-size: 12px;
}

.file-status {
  display: flex;
  align-items: center;
  gap: 5px;
  margin-top: 7px;
  color: #8a6d72;
  font-size: 12px;
}

.file-status.done {
  color: #2e7d4f;
}

.file-status.failed {
  color: #c0392b;
}

.remove-btn {
  display: flex;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  color: #c08a92;
}

.remove-btn:hover {
  background: #fbecee;
  color: #a11d2e;
}

.actions {
  display: flex;
  gap: 10px;
  margin-top: 22px;
}

.upload-btn {
  display: flex;
  flex: 1;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 46px;
  border-radius: 8px;
  background: #a11d2e;
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
}

.upload-btn:hover:not(:disabled) {
  background: #86182a;
}

.upload-btn:disabled {
  background: #e3c3c8;
  cursor: not-allowed;
}

.clear-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  height: 46px;
  padding: 0 18px;
  border: 1px solid #e6c2c7;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 14px;
}

.clear-btn:disabled {
  color: #c9a4aa;
  cursor: not-allowed;
}

.spin {
  animation: rotate 0.9s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

.result-box {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  margin-top: 18px;
  padding: 13px 14px;
  border-radius: 8px;
  font-size: 13px;
}

.result-box.success {
  background: #fbecee;
  border: 1px solid #e6c2c7;
  color: #801724;
}

.result-box.error {
  background: #fff1f2;
  border: 1px solid #f0cdd1;
  color: #b81f30;
}

@media (max-width: 767px) {
  .upload-nav {
    padding: 0 12px;
  }

  .nav-brand {
    display: none;
  }

  .nav-documents {
    display: none;
  }

  .upload-main {
    padding: 24px 12px 40px;
  }

  .upload-panel {
    padding: 22px 16px;
  }

  .actions {
    flex-direction: column;
  }
}
</style>
