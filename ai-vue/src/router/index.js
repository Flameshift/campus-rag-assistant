import { createRouter, createWebHistory } from 'vue-router'
import HomeView from '../views/HomeView.vue'
import ChatView from '../views/ChatView.vue'
import UploadView from '../views/UploadView.vue'
import AuthView from '../views/AuthView.vue'
import DocumentManagementView from '../views/DocumentManagementView.vue'
import { getAuthToken, getStoredUser } from '../api/auth'

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes: [
    { path: '/', name: 'home', component: HomeView },
    { path: '/chat', name: 'chat', component: ChatView },
    { path: '/upload', name: 'upload', component: UploadView, meta: { requiresAdmin: true } },
    { path: '/documents', name: 'documents', component: DocumentManagementView, meta: { requiresAdmin: true } },
    { path: '/auth', name: 'auth', component: AuthView }
  ],
  scrollBehavior() {
    return { top: 0 }
  }
})

router.beforeEach((to) => {
  if (!to.meta.requiresAdmin) return true
  if (!getAuthToken()) return { path: '/auth', query: { redirect: to.fullPath } }
  const user = getStoredUser()
  if (user?.role !== 'ADMIN') return '/chat'
  return true
})

export default router
