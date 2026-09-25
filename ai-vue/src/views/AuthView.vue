<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ArrowLeft, CircleAlert, LoaderCircle, Lock, LogIn, Sparkles, UserRound } from '@lucide/vue'
import { loginUser, registerUser, setAuth } from '../api/auth'

const router = useRouter()

const mode = ref('login')
const username = ref('')
const password = ref('')
const submitting = ref(false)
const error = ref('')

function switchMode(nextMode) {
  mode.value = nextMode
  error.value = ''
}

async function submit() {
  if (submitting.value) return
  const name = username.value.trim()
  if (!name || password.value.length < 6) {
    error.value = '请输入用户名，密码至少 6 位'
    return
  }

  submitting.value = true
  error.value = ''
  try {
    const data =
      mode.value === 'register'
        ? await registerUser({ username: name, password: password.value })
        : await loginUser({ username: name, password: password.value })

    // 后端返回约定：{ token, user: { id, username } }
    setAuth(data.token, data.user)
    router.push('/chat')
  } catch (err) {
    error.value = err.message || (mode.value === 'register' ? '注册失败' : '登录失败')
  } finally {
    submitting.value = false
  }
}
</script>

<template>
  <div class="auth-page">
    <header class="auth-nav">
      <button class="back-btn" type="button" @click="router.push('/')">
        <ArrowLeft :size="17" />返回首页
      </button>
      <div class="nav-brand">
        <span class="brand-mark"><Sparkles :size="16" /></span>
        <span>AI 咨询助手</span>
      </div>
      <RouterLink class="guest-link" to="/chat">游客进入</RouterLink>
    </header>

    <main class="auth-main">
      <div class="auth-panel">
        <div class="auth-tabs">
          <button type="button" :class="{ active: mode === 'login' }" @click="switchMode('login')">登录</button>
          <button type="button" :class="{ active: mode === 'register' }" @click="switchMode('register')">注册</button>
        </div>

        <h1>{{ mode === 'login' ? '欢迎回来' : '创建账号' }}</h1>
        <p class="auth-sub">登录后对话记录会保存到你的账号，游客模式不会保存任何内容。</p>

        <form class="auth-form" @submit.prevent="submit">
          <label>
            <span>用户名</span>
            <div class="field-box">
              <UserRound :size="16" />
              <input v-model="username" type="text" autocomplete="username" placeholder="请输入用户名" />
            </div>
          </label>

          <label>
            <span>密码</span>
            <div class="field-box">
              <Lock :size="16" />
              <input
                v-model="password"
                type="password"
                autocomplete="current-password"
                placeholder="至少 6 位"
              />
            </div>
          </label>

          <div v-if="error" class="auth-error">
            <CircleAlert :size="16" />
            <span>{{ error }}</span>
          </div>

          <button class="submit-btn" type="submit" :disabled="submitting">
            <LoaderCircle v-if="submitting" class="spin" :size="18" />
            <LogIn v-else :size="18" />
            {{ submitting ? '处理中…' : mode === 'login' ? '登录' : '注册并登录' }}
          </button>
        </form>

        <p class="guest-hint">
          暂时不想登录？
          <RouterLink to="/chat">以游客身份开始对话</RouterLink>
        </p>
      </div>
    </main>
  </div>
</template>

<style scoped>
.auth-page {
  min-height: 100dvh;
  background: #ffffff;
  color: #38292c;
}

.auth-nav {
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

.guest-link {
  padding: 8px 14px;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 13px;
  font-weight: 600;
  text-decoration: none;
}

.guest-link:hover {
  background: #fbecee;
}

.auth-main {
  display: flex;
  justify-content: center;
  padding: 56px 20px 72px;
}

.auth-panel {
  width: 100%;
  max-width: 440px;
  padding: 30px;
  border: 1px solid #e9ccd1;
  border-radius: 8px;
  background: #fffdfd;
  box-shadow: 0 10px 30px rgba(120, 20, 32, 0.06);
}

.auth-tabs {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 6px;
  padding: 4px;
  border: 1px solid #f0d5d8;
  border-radius: 8px;
  background: #fdf7f8;
}

.auth-tabs button {
  height: 36px;
  border-radius: 6px;
  color: #8a6d72;
  font-size: 14px;
  font-weight: 600;
}

.auth-tabs button.active {
  background: #a11d2e;
  color: #ffffff;
}

.auth-panel h1 {
  margin-top: 24px;
  font-size: 24px;
  color: #801724;
}

.auth-sub {
  margin-top: 8px;
  color: #8a6d72;
  font-size: 13px;
  line-height: 1.7;
}

.auth-form {
  display: flex;
  flex-direction: column;
  gap: 16px;
  margin-top: 24px;
}

.auth-form label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  color: #38292c;
  font-size: 13px;
  font-weight: 600;
}

.field-box {
  display: flex;
  align-items: center;
  gap: 10px;
  height: 42px;
  padding: 0 12px;
  border: 1px solid #e6c2c7;
  border-radius: 8px;
  color: #b08a90;
  background: #ffffff;
}

.field-box:focus-within {
  border-color: #a11d2e;
  box-shadow: 0 0 0 3px rgba(161, 29, 46, 0.1);
}

.field-box input {
  flex: 1;
  min-width: 0;
  font-size: 14px;
}

.auth-error {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px 12px;
  border-radius: 8px;
  background: #fff1f2;
  border: 1px solid #f0cdd1;
  color: #b81f30;
  font-size: 13px;
}

.submit-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  height: 44px;
  border-radius: 8px;
  background: #a11d2e;
  color: #ffffff;
  font-size: 15px;
  font-weight: 600;
}

.submit-btn:hover:not(:disabled) {
  background: #86182a;
}

.submit-btn:disabled {
  background: #e3c3c8;
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

.guest-hint {
  margin-top: 18px;
  color: #8a6d72;
  font-size: 13px;
  text-align: center;
}

.guest-hint a {
  color: #a11d2e;
  font-weight: 600;
  text-decoration: none;
}

@media (max-width: 767px) {
  .auth-nav {
    padding: 0 12px;
  }

  .nav-brand {
    display: none;
  }

  .auth-main {
    padding: 28px 12px 48px;
  }

  .auth-panel {
    padding: 22px 16px;
  }
}
</style>
