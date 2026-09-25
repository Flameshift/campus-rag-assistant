<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowLeft,
  CircleAlert,
  CircleCheck,
  Clock3,
  Database,
  FilePlus2,
  FileText,
  History,
  LoaderCircle,
  MoreHorizontal,
  RefreshCw,
  RotateCcw,
  Search,
  Sparkles,
  Trash2,
  X
} from '@lucide/vue'
import {
  deleteDocument,
  activateDocumentVersion,
  disableDocument,
  listDocumentVersions,
  listDocumentTasks,
  listDocuments,
  reindexDocument,
  restoreDocument,
  uploadDocumentVersion
} from '../api/documents'

const router = useRouter()

const documents = ref([])
const tasks = ref([])
const loading = ref(true)
const demoMode = ref(false)
const query = ref('')
const statusFilter = ref('all')
const actionBusy = ref('')
const toast = ref('')
const replaceTarget = ref(null)
const replaceInput = ref(null)
const replaceProgress = ref(0)
const deleteTarget = ref(null)
const taskTarget = ref(null)
const actionTarget = ref(null)
const versionTarget = ref(null)
const versions = ref([])
const versionsLoading = ref(false)
const actionMenuPosition = ref({ top: 0, left: 0 })
let toastTimer = null

const demoDocuments = [
  {
    id: 'doc-handbook',
    name: '学生手册20240906.pdf',
    type: 'PDF',
    version: 'v2',
    status: 'active',
    chunks: 714,
    parents: 667,
    size: '8.6 MB',
    updatedAt: '2026-09-18 01:20',
    owner: '管理员'
  },
  {
    id: 'doc-scholarship',
    name: '奖学金评审办法.docx',
    type: 'DOCX',
    version: 'v1',
    status: 'processing',
    chunks: 126,
    parents: 38,
    size: '1.2 MB',
    updatedAt: '2026-09-18 01:42',
    owner: '管理员'
  },
  {
    id: 'doc-freshman',
    name: '新生入学指南.pdf',
    type: 'PDF',
    version: 'v1',
    status: 'disabled',
    chunks: 93,
    parents: 31,
    size: '3.4 MB',
    updatedAt: '2026-09-17 18:30',
    owner: '管理员'
  },
  {
    id: 'doc-dictionary',
    name: '业务数据字典.xlsx',
    type: 'XLSX',
    version: 'v1',
    status: 'failed',
    chunks: 0,
    parents: 0,
    size: '640 KB',
    updatedAt: '2026-09-17 14:12',
    owner: '管理员'
  }
]

const demoTasks = [
  {
    id: 'task-20260918-001',
    documentId: 'doc-scholarship',
    document: '奖学金评审办法.docx',
    type: '上传新版本',
    status: 'running',
    stage: 'embedding',
    progress: 68,
    startedAt: '2026-09-18 01:42',
    message: '正在生成向量'
  },
  {
    id: 'task-20260918-002',
    documentId: 'doc-handbook',
    document: '学生手册20240906.pdf',
    type: '重新索引',
    status: 'completed',
    stage: 'activated',
    progress: 100,
    startedAt: '2026-09-18 01:20',
    message: '索引已切换为 active'
  },
  {
    id: 'task-20260917-009',
    documentId: 'doc-dictionary',
    document: '业务数据字典.xlsx',
    type: '上传',
    status: 'failed',
    stage: 'parsing',
    progress: 24,
    startedAt: '2026-09-17 14:12',
    message: '工作表表头无法识别'
  }
]

const statusMeta = {
  active: { label: '生效中', tone: 'success' },
  processing: { label: '处理中', tone: 'processing' },
  disabled: { label: '已停用', tone: 'muted' },
  failed: { label: '失败', tone: 'danger' }
}

const filteredDocuments = computed(() => {
  const keyword = query.value.trim().toLowerCase()
  return documents.value.filter((document) => {
    const statusMatched = statusFilter.value === 'all' || document.status === statusFilter.value
    const keywordMatched =
      !keyword ||
      document.name.toLowerCase().includes(keyword) ||
      document.type.toLowerCase().includes(keyword)
    return statusMatched && keywordMatched
  })
})

const summary = computed(() => ({
  total: documents.value.length,
  active: documents.value.filter((item) => item.status === 'active').length,
  processing: documents.value.filter((item) => item.status === 'processing').length,
  failed: documents.value.filter((item) => item.status === 'failed').length
}))

const visibleTasks = computed(() => {
  if (!taskTarget.value) return tasks.value
  return tasks.value.filter((task) => task.documentId === taskTarget.value.id)
})

const actionOptions = computed(() => {
  const document = actionTarget.value
  if (!document) return []
  return [
    {
      key: 'replace',
      icon: FilePlus2,
      label: '上传新版本',
      description: '用新文件构建 staging 版本，成功后再切换'
    },
    {
      key: 'reindex',
      icon: RefreshCw,
      label: '重新索引',
      description: '保留原文件，重新解析、分块和生成向量'
    },
    document.status === 'disabled'
      ? {
          key: 'restore',
          icon: RotateCcw,
          label: '恢复文档',
          description: '重新让该文档参与知识库检索'
        }
      : {
          key: 'disable',
          icon: CircleAlert,
          label: '停用文档',
          description: '暂时停止检索，但保留数据用于恢复'
        },
    {
      key: 'versions',
      icon: Database,
      label: '版本记录',
      description: '查看历史版本并切换到指定版本'
    },
    {
      key: 'tasks',
      icon: History,
      label: '查看任务',
      description: '查看上传、索引、删除任务的进度和错误'
    },
    {
      key: 'delete',
      icon: Trash2,
      label: '删除文档',
      description: '移除源文档及其分块、向量和索引关系',
      danger: true
    }
  ]
})

const actionMenuStyle = computed(() => ({
  top: `${actionMenuPosition.value.top}px`,
  left: `${actionMenuPosition.value.left}px`
}))

function showToast(message) {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2400)
}

function addTask(document, type, status = 'completed', stage = 'activated', message = '任务已完成') {
  const now = new Date()
  const stamp = [
    now.getFullYear(),
    String(now.getMonth() + 1).padStart(2, '0'),
    String(now.getDate()).padStart(2, '0'),
    String(now.getHours()).padStart(2, '0'),
    String(now.getMinutes()).padStart(2, '0')
  ].join('')
  tasks.value.unshift({
    id: `task-${stamp}-${String(tasks.value.length + 1).padStart(3, '0')}`,
    documentId: document.id,
    document: document.name,
    type,
    status,
    stage,
    progress: status === 'completed' ? 100 : status === 'failed' ? 0 : 45,
    startedAt: now.toLocaleString('zh-CN', { hour12: false }),
    message
  })
}

async function loadDocuments() {
  loading.value = true
  try {
    const data = await listDocuments()
    documents.value = Array.isArray(data) ? data : data.documents || []
    demoMode.value = false
    const taskData = await listDocumentTasks()
    tasks.value = Array.isArray(taskData) ? taskData : taskData.tasks || []
  } catch {
    documents.value = demoDocuments.map((document) => ({ ...document }))
    tasks.value = demoTasks.map((task) => ({ ...task }))
    demoMode.value = true
  } finally {
    loading.value = false
  }
}

async function runAction(document, action) {
  if (actionBusy.value || document.status === 'processing') return
  actionBusy.value = `${document.id}:${action}`
  try {
    if (action === 'reindex') {
      if (!demoMode.value) await reindexDocument(document.id)
      document.status = 'processing'
      addTask(document, '重新索引', 'running', 'embedding', '正在重建向量与父级元数据')
      showToast('重新索引任务已提交')
      if (demoMode.value) {
        window.setTimeout(() => {
          document.status = 'active'
          const task = tasks.value.find(
            (item) => item.documentId === document.id && item.status === 'running'
          )
          if (task) {
            task.status = 'completed'
            task.stage = 'activated'
            task.progress = 100
            task.message = '索引已切换为 active'
          }
        }, 1600)
      }
    } else if (action === 'disable') {
      if (!demoMode.value) await disableDocument(document.id)
      document.status = 'disabled'
      addTask(document, '停用文档', 'completed', 'disabled', '文档已停止参与检索')
      showToast('文档已停用')
    } else if (action === 'restore') {
      if (!demoMode.value) await restoreDocument(document.id)
      document.status = 'active'
      addTask(document, '恢复文档', 'completed', 'activated', '文档已重新参与检索')
      showToast('文档已恢复')
    }
  } catch (error) {
    showToast(error.message || '操作失败')
  } finally {
    actionBusy.value = ''
  }
}

function openReplace(document) {
  actionTarget.value = null
  replaceTarget.value = document
  replaceProgress.value = 0
  requestAnimationFrame(() => replaceInput.value?.click())
}

async function onReplaceFile(event) {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file || !replaceTarget.value) return
  replaceProgress.value = 1
  actionBusy.value = `${replaceTarget.value.id}:replace`
  try {
    if (!demoMode.value) {
      await uploadDocumentVersion(replaceTarget.value.id, file, (value) => {
        replaceProgress.value = value
      })
    } else {
      replaceProgress.value = 100
    }
    replaceTarget.value.name = file.name
    replaceTarget.value.type = file.name.split('.').pop()?.toUpperCase() || 'FILE'
    replaceTarget.value.version = `v${Number(replaceTarget.value.version.slice(1) || 1) + 1}`
    replaceTarget.value.status = 'processing'
    replaceTarget.value.updatedAt = new Date().toLocaleString('zh-CN', { hour12: false })
    addTask(replaceTarget.value, '上传新版本', 'running', 'embedding', '正在构建 staging 索引')
    showToast('新版本已上传，正在构建索引')
  } catch (error) {
    showToast(error.message || '上传失败')
  } finally {
    replaceTarget.value = null
    replaceProgress.value = 0
    actionBusy.value = ''
  }
}

function confirmDelete(document) {
  actionTarget.value = null
  deleteTarget.value = document
}

async function removeDocument() {
  const document = deleteTarget.value
  if (!document) return
  actionBusy.value = `${document.id}:delete`
  try {
    if (!demoMode.value) await deleteDocument(document.id)
    documents.value = documents.value.filter((item) => item.id !== document.id)
    addTask(document, '删除文档', 'completed', 'deleted', '文档已从知识库移除')
    showToast('文档已删除')
  } catch (error) {
    showToast(error.message || '删除失败')
  } finally {
    deleteTarget.value = null
    actionBusy.value = ''
  }
}

function openTasks(document) {
  actionTarget.value = null
  taskTarget.value = document
}

async function openVersions(document) {
  actionTarget.value = null
  versionTarget.value = document
  versionsLoading.value = true
  try {
    if (demoMode.value) {
      versions.value = [
        {
          id: document.id,
          version: Number(document.version.slice(1) || 1),
          status: 'active',
          current: true,
          name: document.name,
          uploader: document.owner,
          createdAt: document.updatedAt
        }
      ]
    } else {
      const data = await listDocumentVersions(document.id)
      versions.value = data.versions || []
    }
  } catch (error) {
    showToast(error.message || '版本加载失败')
    versions.value = []
  } finally {
    versionsLoading.value = false
  }
}

async function activateVersion(version) {
  if (version.current) return
  actionBusy.value = `${version.id}:activate`
  try {
    if (!demoMode.value) await activateDocumentVersion(version.id)
    versions.value = versions.value.map((item) => ({
      ...item,
      current: item.id === version.id,
      status: item.id === version.id ? 'active' : 'retired'
    }))
    if (versionTarget.value) {
      versionTarget.value.version = `v${version.version}`
      versionTarget.value.name = version.name
      versionTarget.value.status = 'active'
    }
    addTask(versionTarget.value, '切换版本', 'completed', 'activated', `已切换到 v${version.version}`)
    showToast(`已切换到 v${version.version}`)
  } catch (error) {
    showToast(error.message || '版本切换失败')
  } finally {
    actionBusy.value = ''
  }
}

function openActions(document, event) {
  if (document.status === 'processing') return
  const menuWidth = 320
  const rect = event.currentTarget.getBoundingClientRect()
  const left = Math.min(
    window.innerWidth - menuWidth - 12,
    Math.max(12, rect.right - menuWidth)
  )
  const estimatedHeight = 430
  const top = Math.min(
    window.innerHeight - estimatedHeight - 12,
    rect.bottom + 6
  )
  actionMenuPosition.value = { top: Math.max(12, top), left }
  actionTarget.value = document
}

function handleActionOption(key) {
  const document = actionTarget.value
  if (!document) return
  if (key === 'replace') openReplace(document)
  else if (key === 'reindex' || key === 'disable' || key === 'restore') {
    actionTarget.value = null
    runAction(document, key)
  } else if (key === 'tasks') openTasks(document)
  else if (key === 'versions') openVersions(document)
  else if (key === 'delete') confirmDelete(document)
}

onMounted(loadDocuments)
</script>

<template>
  <div class="documents-page">
    <header class="documents-nav">
      <button class="back-btn" type="button" @click="router.push('/chat')">
        <ArrowLeft :size="17" />返回对话
      </button>
      <div class="nav-brand">
        <span class="brand-mark"><Sparkles :size="16" /></span>
        <span>AI 咨询助手</span>
      </div>
      <RouterLink class="nav-upload" to="/upload">
        <FilePlus2 :size="16" />上传新文档
      </RouterLink>
    </header>

    <main class="documents-main">
      <section class="page-heading">
        <div class="heading-copy">
          <span class="page-icon"><Database :size="22" /></span>
          <div>
            <h1>知识库文档</h1>
            <p>管理已上传的源文档和索引版本，不展示内部向量内容</p>
          </div>
        </div>
        <span v-if="demoMode" class="demo-badge">本地演示数据</span>
      </section>

      <section class="summary-grid">
        <article class="summary-card">
          <span>全部文档</span>
          <strong>{{ summary.total }}</strong>
          <FileText :size="20" />
        </article>
        <article class="summary-card success">
          <span>生效中</span>
          <strong>{{ summary.active }}</strong>
          <CircleCheck :size="20" />
        </article>
        <article class="summary-card processing">
          <span>处理中</span>
          <strong>{{ summary.processing }}</strong>
          <LoaderCircle :size="20" />
        </article>
        <article class="summary-card danger">
          <span>异常</span>
          <strong>{{ summary.failed }}</strong>
          <CircleAlert :size="20" />
        </article>
      </section>

      <section class="document-panel">
        <div class="toolbar">
          <label class="search-field">
            <Search :size="16" />
            <input v-model="query" type="search" placeholder="搜索文档名称或格式" />
          </label>
          <div class="status-tabs">
            <button :class="{ active: statusFilter === 'all' }" @click="statusFilter = 'all'">全部</button>
            <button :class="{ active: statusFilter === 'active' }" @click="statusFilter = 'active'">生效中</button>
            <button :class="{ active: statusFilter === 'processing' }" @click="statusFilter = 'processing'">处理中</button>
            <button :class="{ active: statusFilter === 'disabled' }" @click="statusFilter = 'disabled'">已停用</button>
            <button :class="{ active: statusFilter === 'failed' }" @click="statusFilter = 'failed'">异常</button>
          </div>
        </div>

        <div v-if="loading" class="state-box">
          <LoaderCircle class="spin" :size="22" />
          <span>正在加载文档列表</span>
        </div>

        <div v-else-if="filteredDocuments.length === 0" class="state-box">
          <Database :size="24" />
          <strong>没有匹配的文档</strong>
          <span>调整筛选条件，或先上传新的知识库资料</span>
        </div>

        <div v-else class="table-wrap">
          <table class="document-table">
            <thead>
              <tr>
                <th>文档</th>
                <th>上传人</th>
                <th>版本</th>
                <th>状态</th>
                <th>分块</th>
                <th>父级</th>
                <th>更新时间</th>
                <th class="actions-col">操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="document in filteredDocuments" :key="document.id">
                <td data-label="文档">
                  <div class="document-name">
                    <span class="file-icon"><FileText :size="18" /></span>
                    <div>
                      <strong>{{ document.name }}</strong>
                      <span>{{ document.type }} · {{ document.size || '未知大小' }} · {{ document.owner || '管理员' }}</span>
                    </div>
                  </div>
                </td>
                <td data-label="上传人">{{ document.owner || '系统历史数据' }}</td>
                <td data-label="版本"><span class="version-text">{{ document.version }}</span></td>
                <td data-label="状态">
                  <span class="status-chip" :class="statusMeta[document.status]?.tone">
                    <CircleCheck v-if="document.status === 'active'" :size="13" />
                    <LoaderCircle v-else-if="document.status === 'processing'" class="spin" :size="13" />
                    <CircleAlert v-else-if="document.status === 'failed'" :size="13" />
                    <Clock3 v-else :size="13" />
                    {{ statusMeta[document.status]?.label || document.status }}
                  </span>
                </td>
                <td data-label="分块">{{ document.chunks }}</td>
                <td data-label="父级">{{ document.parents }}</td>
                <td data-label="更新时间">{{ document.updatedAt }}</td>
                <td data-label="操作">
                  <div class="row-actions">
                    <button
                      class="more-btn"
                      :disabled="document.status === 'processing'"
                      @click.stop="openActions(document, $event)"
                    >
                      <MoreHorizontal :size="16" />
                      <span>更多</span>
                    </button>
                  </div>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </main>

    <input
      ref="replaceInput"
      type="file"
      accept=".pdf,.docx,.txt,.md,.html,.csv,.json,.xlsx"
      hidden
      @change="onReplaceFile"
    />

    <div v-if="taskTarget" class="drawer-mask" @click.self="taskTarget = null">
      <aside class="task-drawer">
        <header>
          <div>
            <span class="drawer-eyebrow">任务记录</span>
            <h2>{{ taskTarget.name }}</h2>
          </div>
          <button class="icon-btn" title="关闭" @click="taskTarget = null"><X :size="18" /></button>
        </header>
        <div class="task-list">
          <article v-for="task in visibleTasks" :key="task.id" class="task-item">
            <span class="task-icon" :class="task.status">
              <CircleCheck v-if="task.status === 'completed'" :size="16" />
              <LoaderCircle v-else-if="task.status === 'running'" class="spin" :size="16" />
              <CircleAlert v-else :size="16" />
            </span>
            <div class="task-copy">
              <div class="task-head">
                <strong>{{ task.type }}</strong>
                <span>{{ task.startedAt }}</span>
              </div>
              <p>{{ task.message }}</p>
              <div class="task-progress">
                <span :style="{ width: `${task.progress}%` }" :class="task.status"></span>
              </div>
              <small>{{ task.stage }} · {{ task.progress }}%</small>
            </div>
          </article>
          <p v-if="visibleTasks.length === 0" class="drawer-empty">该文档暂无任务记录</p>
        </div>
      </aside>
    </div>

    <div v-if="versionTarget" class="drawer-mask" @click.self="versionTarget = null">
      <aside class="task-drawer">
        <header>
          <div>
            <span class="drawer-eyebrow">版本记录</span>
            <h2>{{ versionTarget.name }}</h2>
          </div>
          <button class="icon-btn" title="关闭" @click="versionTarget = null"><X :size="18" /></button>
        </header>
        <div v-if="versionsLoading" class="state-box">
          <LoaderCircle class="spin" :size="20" />
          <span>正在加载版本</span>
        </div>
        <div v-else class="version-list">
          <article v-for="version in versions" :key="version.id" class="version-item">
            <div class="version-item-head">
              <strong>v{{ version.version }}</strong>
              <span class="status-chip" :class="version.current ? 'success' : 'muted'">
                {{ version.current ? '当前生效' : version.status }}
              </span>
            </div>
            <p>{{ version.name }}</p>
            <small>{{ version.uploader }} · {{ version.createdAt }}</small>
            <button
              v-if="!version.current"
              class="version-action"
              :disabled="!!actionBusy"
              @click="activateVersion(version)"
            >
              切换到该版本
            </button>
          </article>
          <p v-if="versions.length === 0" class="drawer-empty">暂无版本记录</p>
        </div>
      </aside>
    </div>

    <Teleport to="body">
      <div v-if="actionTarget" class="action-menu-layer" @click.self="actionTarget = null">
        <section class="floating-action-menu" :style="actionMenuStyle" @click.stop>
          <header class="action-menu-head">
            <div>
              <span>{{ actionTarget.name }}</span>
              <small>{{ actionTarget.version }} · {{ actionTarget.chunks }} 个分块</small>
            </div>
            <button class="icon-btn" title="关闭" @click="actionTarget = null"><X :size="17" /></button>
          </header>
          <div class="action-options">
            <button
              v-for="option in actionOptions"
              :key="option.key"
              class="action-option"
              :class="{ danger: option.danger }"
              @click="handleActionOption(option.key)"
            >
              <span class="action-option-icon"><component :is="option.icon" :size="17" /></span>
              <span class="action-option-copy">
                <strong>{{ option.label }}</strong>
                <small>{{ option.description }}</small>
              </span>
            </button>
          </div>
        </section>
      </div>
    </Teleport>

    <div v-if="deleteTarget" class="modal-mask" @click.self="deleteTarget = null">
      <section class="confirm-modal">
        <span class="modal-icon"><Trash2 :size="20" /></span>
        <h2>删除文档</h2>
        <p>
          将删除「{{ deleteTarget.name }}」及其分块、向量和索引关系。历史对话会保留，
          但相关引用可能失效。
        </p>
        <div class="modal-actions">
          <button class="secondary-btn" @click="deleteTarget = null">取消</button>
          <button class="danger-btn" :disabled="!!actionBusy" @click="removeDocument">确认删除</button>
        </div>
      </section>
    </div>

    <div v-if="replaceProgress > 0" class="upload-toast">
      <LoaderCircle class="spin" :size="16" />
      正在上传新版本 {{ replaceProgress }}%
    </div>

    <transition name="toast">
      <div v-if="toast" class="page-toast">{{ toast }}</div>
    </transition>
  </div>
</template>

<style scoped>
.documents-page {
  min-height: 100dvh;
  background: #fffafa;
  color: #38292c;
}

.documents-nav {
  position: sticky;
  top: 0;
  z-index: 20;
  display: flex;
  align-items: center;
  gap: 12px;
  height: 64px;
  padding: 0 24px;
  background: rgba(255, 255, 255, 0.94);
  border-bottom: 1px solid #f0d5d8;
  backdrop-filter: blur(12px);
}

.back-btn,
.nav-upload {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 36px;
  padding: 0 12px;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.back-btn:hover,
.nav-upload:hover {
  background: #fbecee;
}

.nav-upload {
  background: #a11d2e;
  color: #fff;
}

.nav-upload:hover {
  background: #86182a;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 auto;
  font-size: 15px;
  font-weight: 700;
}

.brand-mark,
.page-icon {
  display: inline-flex;
  width: 34px;
  height: 34px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #a11d2e;
  color: #fff;
}

.documents-main {
  width: 100%;
  max-width: 1180px;
  margin: 0 auto;
  padding: 34px 24px 70px;
}

.page-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 18px;
  margin-bottom: 22px;
}

.heading-copy {
  display: flex;
  align-items: center;
  gap: 14px;
}

.page-icon {
  width: 46px;
  height: 46px;
  flex: 0 0 46px;
  background: #fbecee;
  color: #a11d2e;
}

.page-heading h1 {
  font-size: 25px;
  color: #801724;
}

.page-heading p {
  margin-top: 4px;
  color: #8a6d72;
  font-size: 13px;
}

.demo-badge {
  padding: 7px 10px;
  border: 1px solid #e6c2c7;
  border-radius: 999px;
  background: #fff4f5;
  color: #a11d2e;
  font-size: 12px;
  font-weight: 600;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.summary-card {
  position: relative;
  display: flex;
  flex-direction: column;
  min-height: 104px;
  padding: 18px;
  border: 1px solid #edd1d5;
  border-radius: 8px;
  background: #fff;
}

.summary-card span {
  color: #8a6d72;
  font-size: 12px;
}

.summary-card strong {
  margin-top: 8px;
  color: #6b232d;
  font-size: 28px;
}

.summary-card svg {
  position: absolute;
  top: 16px;
  right: 16px;
  color: #b08a90;
}

.summary-card.success {
  border-color: #d7eadf;
}

.summary-card.success strong,
.summary-card.success svg {
  color: #2e7d4f;
}

.summary-card.processing strong,
.summary-card.processing svg {
  color: #b16a1d;
}

.summary-card.danger {
  border-color: #f0cdd1;
}

.summary-card.danger strong,
.summary-card.danger svg {
  color: #c0392b;
}

.document-panel {
  border: 1px solid #edd1d5;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}

.toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 15px 16px;
  border-bottom: 1px solid #f1dcdf;
}

.search-field {
  display: flex;
  align-items: center;
  gap: 8px;
  width: min(320px, 100%);
  height: 38px;
  padding: 0 11px;
  border: 1px solid #e6c2c7;
  border-radius: 8px;
  background: #fff;
  color: #b08a90;
}

.search-field:focus-within {
  border-color: #a11d2e;
}

.search-field input {
  flex: 1;
  min-width: 0;
  font-size: 13px;
}

.status-tabs {
  display: flex;
  align-items: center;
  gap: 3px;
  padding: 3px;
  border: 1px solid #f0d5d8;
  border-radius: 8px;
  background: #fff8f8;
}

.status-tabs button {
  height: 30px;
  padding: 0 10px;
  border-radius: 6px;
  color: #8a6d72;
  font-size: 12px;
}

.status-tabs button.active {
  background: #fff;
  color: #a11d2e;
  font-weight: 700;
  box-shadow: 0 2px 8px rgba(120, 20, 32, 0.08);
}

.table-wrap {
  overflow-x: auto;
}

.document-table {
  width: 100%;
  min-width: 980px;
  border-collapse: collapse;
}

.document-table th {
  padding: 12px 14px;
  background: #fffafa;
  border-bottom: 1px solid #f1dcdf;
  color: #9a7379;
  font-size: 12px;
  font-weight: 600;
  text-align: left;
  white-space: nowrap;
}

.document-table td {
  padding: 14px;
  border-bottom: 1px solid #f5e8ea;
  color: #5d474b;
  font-size: 13px;
  vertical-align: middle;
}

.document-table tbody tr:hover {
  background: #fffafa;
}

.actions-col {
  width: 132px;
}

.document-name {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 260px;
}

.file-icon {
  display: flex;
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #a11d2e;
}

.document-name div {
  min-width: 0;
}

.document-name strong,
.document-name span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.document-name strong {
  max-width: 280px;
  color: #38292c;
}

.document-name span {
  max-width: 280px;
  margin-top: 3px;
  color: #a4858a;
  font-size: 11px;
}

.version-text {
  display: inline-flex;
  padding: 4px 8px;
  border-radius: 6px;
  background: #f7f1f2;
  color: #6b232d;
  font-weight: 600;
}

.status-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 8px;
  border-radius: 999px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.status-chip.success {
  background: #eff8f2;
  color: #2e7d4f;
}

.status-chip.processing {
  background: #fff7e9;
  color: #a96518;
}

.status-chip.muted {
  background: #f3f4f6;
  color: #6b7280;
}

.status-chip.danger {
  background: #fff1f2;
  color: #c0392b;
}

.row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.more-btn,
.icon-btn {
  display: inline-flex;
  height: 32px;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 0 8px;
  border-radius: 8px;
  color: #80666b;
  font-size: 12px;
  white-space: nowrap;
}

.more-btn {
  padding: 0 10px;
  border: 1px solid #e6c2c7;
  background: #fff8f8;
  color: #8f1a28;
  font-weight: 600;
}

.more-btn:hover:not(:disabled),
.icon-btn:hover {
  background: #fbecee;
  color: #a11d2e;
  border-color: #e6c2c7;
}

.more-btn:disabled {
  color: #d0bfc2;
  cursor: not-allowed;
}

.state-box {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 8px;
  min-height: 240px;
  color: #9a7379;
  text-align: center;
}

.state-box strong {
  color: #6b232d;
}

.state-box span {
  font-size: 12px;
}

.spin {
  animation: rotate 0.9s linear infinite;
}

@keyframes rotate {
  to {
    transform: rotate(360deg);
  }
}

.drawer-mask,
.modal-mask {
  position: fixed;
  inset: 0;
  z-index: 50;
  display: flex;
  justify-content: flex-end;
  background: rgba(44, 22, 26, 0.28);
}

.task-drawer {
  width: min(440px, 100%);
  height: 100%;
  padding: 22px;
  background: #fff;
  box-shadow: -16px 0 40px rgba(80, 20, 30, 0.12);
  overflow-y: auto;
}

.task-drawer header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 18px;
  border-bottom: 1px solid #f0d5d8;
}

.drawer-eyebrow {
  color: #a11d2e;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.task-drawer h2 {
  margin-top: 5px;
  color: #6b232d;
  font-size: 18px;
}

.task-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 16px;
}

.task-item {
  display: flex;
  gap: 10px;
  padding: 13px;
  border: 1px solid #efd9dc;
  border-radius: 8px;
  background: #fffdfd;
}

.task-icon {
  display: flex;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
}

.task-icon.completed {
  background: #eff8f2;
  color: #2e7d4f;
}

.task-icon.running {
  background: #fff7e9;
  color: #a96518;
}

.task-icon.failed {
  background: #fff1f2;
  color: #c0392b;
}

.task-copy {
  flex: 1;
  min-width: 0;
}

.task-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.task-head span {
  color: #ad9296;
  font-size: 11px;
}

.task-copy p,
.task-copy small {
  display: block;
  margin-top: 5px;
  color: #8a6d72;
  font-size: 12px;
}

.task-progress {
  height: 5px;
  margin-top: 9px;
  border-radius: 999px;
  background: #f4dfe2;
  overflow: hidden;
}

.task-progress span {
  display: block;
  height: 100%;
  border-radius: inherit;
  background: #a11d2e;
}

.task-progress span.running {
  background: #d88b32;
}

.task-progress span.failed {
  background: #c0392b;
}

.drawer-empty {
  padding: 28px 0;
  color: #a4858a;
  text-align: center;
}

.version-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding-top: 16px;
}

.version-item {
  padding: 13px;
  border: 1px solid #efd9dc;
  border-radius: 8px;
  background: #fffdfd;
}

.version-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}

.version-item-head strong {
  color: #6b232d;
  font-size: 15px;
}

.version-item p {
  margin-top: 8px;
  color: #4b3539;
  font-size: 13px;
}

.version-item small {
  display: block;
  margin-top: 4px;
  color: #a4858a;
  font-size: 11px;
}

.version-action {
  margin-top: 10px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid #e6c2c7;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 12px;
  font-weight: 600;
}

.version-action:hover:not(:disabled) {
  background: #fbecee;
}

.modal-mask {
  align-items: center;
  justify-content: center;
  padding: 18px;
}

.action-menu-layer {
  position: fixed;
  inset: 0;
  z-index: 80;
  background: rgba(44, 22, 26, 0.03);
}

.floating-action-menu {
  position: fixed;
  width: 320px;
  border: 1px solid #ead0d4;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 18px 50px rgba(80, 20, 30, 0.18);
  overflow: hidden;
}

.action-menu-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  padding: 12px 13px;
  border-bottom: 1px solid #f2dfe2;
  background: #fffafa;
}

.action-menu-head div {
  min-width: 0;
}

.action-menu-head span,
.action-menu-head small {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.action-menu-head span {
  color: #4b3539;
  font-size: 13px;
  font-weight: 700;
}

.action-menu-head small {
  margin-top: 2px;
  color: #a4858a;
  font-size: 11px;
}

.action-options {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 6px;
}

.action-option {
  display: flex;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px;
  border-radius: 8px;
  text-align: left;
}

.action-option:hover {
  background: #fff5f6;
}

.action-option.danger:hover {
  background: #fff1f2;
}

.action-option-icon {
  display: flex;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #a11d2e;
}

.action-option.danger .action-option-icon {
  background: #fff1f2;
  color: #c0392b;
}

.action-option-copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.action-option-copy strong {
  color: #4b3539;
  font-size: 13px;
}

.action-option.danger .action-option-copy strong {
  color: #b22534;
}

.action-option-copy small {
  margin-top: 3px;
  color: #9a7379;
  font-size: 11px;
  line-height: 1.5;
}

.confirm-modal {
  width: min(430px, 100%);
  padding: 24px;
  border-radius: 8px;
  background: #fff;
  box-shadow: 0 20px 60px rgba(80, 20, 30, 0.2);
}

.modal-icon {
  display: flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fff1f2;
  color: #c0392b;
}

.confirm-modal h2 {
  margin-top: 14px;
  color: #6b232d;
  font-size: 20px;
}

.confirm-modal p {
  margin-top: 9px;
  color: #8a6d72;
  font-size: 13px;
  line-height: 1.7;
}

.modal-actions {
  display: flex;
  justify-content: flex-end;
  gap: 9px;
  margin-top: 22px;
}

.secondary-btn,
.danger-btn {
  height: 38px;
  padding: 0 15px;
  border-radius: 8px;
  font-size: 13px;
  font-weight: 600;
}

.secondary-btn {
  border: 1px solid #e6c2c7;
  color: #8f1a28;
}

.danger-btn {
  background: #a11d2e;
  color: #fff;
}

.danger-btn:disabled {
  background: #d6a7ae;
}

.upload-toast,
.page-toast {
  position: fixed;
  z-index: 80;
  display: flex;
  align-items: center;
  gap: 8px;
  border-radius: 8px;
  box-shadow: 0 10px 30px rgba(80, 20, 30, 0.16);
}

.upload-toast {
  right: 22px;
  bottom: 22px;
  padding: 11px 14px;
  background: #fff;
  border: 1px solid #e6c2c7;
  color: #8f1a28;
  font-size: 13px;
}

.page-toast {
  top: 18px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 16px;
  background: #20242c;
  color: #fff;
  font-size: 13px;
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

@media (max-width: 900px) {
  .summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .search-field {
    width: 100%;
  }

  .status-tabs {
    width: 100%;
    overflow-x: auto;
  }
}

@media (max-width: 720px) {
  .documents-nav {
    padding: 0 12px;
  }

  .nav-brand {
    display: none;
  }

  .nav-upload {
    margin-left: auto;
  }

  .documents-main {
    padding: 24px 12px 50px;
  }

  .page-heading {
    align-items: flex-start;
  }

  .page-heading h1 {
    font-size: 21px;
  }

  .table-wrap {
    overflow: visible;
    padding: 10px;
  }

  .document-table,
  .document-table thead,
  .document-table tbody,
  .document-table tr,
  .document-table td {
    display: block;
    min-width: 0;
    width: 100%;
  }

  .document-table thead {
    display: none;
  }

  .document-table tr {
    margin-bottom: 10px;
    padding: 13px;
    border: 1px solid #efd9dc;
    border-radius: 8px;
  }

  .document-table td {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
    padding: 7px 0;
    border: 0;
  }

  .document-table td::before {
    content: attr(data-label);
    color: #a4858a;
    font-size: 11px;
  }

  .document-table td:first-child {
    align-items: flex-start;
  }

  .document-table td:first-child::before {
    display: none;
  }

  .document-name {
    min-width: 0;
  }

  .document-name strong,
  .document-name span {
    max-width: 210px;
  }

  .row-actions {
    display: flex;
    justify-content: flex-end;
    min-width: 0;
  }
}
</style>
