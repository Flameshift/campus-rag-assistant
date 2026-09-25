<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  ArrowUpRight,
  BookOpen,
  BrainCircuit,
  ChevronDown,
  FileText,
  Globe,
  GraduationCap,
  HeartHandshake,
  Lightbulb,
  Mic,
  Rocket,
  Send,
  Sparkles
} from '@lucide/vue'
import HeroStarfield from '../components/HeroStarfield.vue'

const scrolled = ref(false)
const toast = ref('')
const router = useRouter()
let toastTimer = null

const features = [
  { icon: BookOpen, title: '学生手册问答', desc: '围绕学籍、考试、奖助、处分和校园生活，直接询问具体规定。' },
  { icon: FileText, title: '依据与来源可追溯', desc: '回答会附带文件、版本、页码和章节，方便回到原文核对。' },
  { icon: Globe, title: '现行与历史版本', desc: '支持询问当前有效规定，也支持按时间查询旧版制度。' },
  { icon: Mic, title: '多轮场景追问', desc: '可以继续补充身份、时间和具体情形，系统会结合上下文理解。' }
]

const scenarios = [
  { icon: GraduationCap, title: '学籍与培养', desc: '入学注册、休复学、转专业、毕业与学位相关问题。', prompt: '本科生最长修业年限一般不超过几年？' },
  { icon: BookOpen, title: '考试与重修', desc: '补考、重修、成绩记载、考核纪律与学业预警。', prompt: '专业必修课挂科后应该重修还是补考？' },
  { icon: HeartHandshake, title: '奖助与评优', desc: '奖学金、助学金、评优条件和申请流程。', prompt: '申请国家励志奖学金通常需要满足哪些条件？' },
  { icon: Lightbulb, title: '宿舍与日常', desc: '宿舍用电、门禁、请假、校园秩序和日常管理。', prompt: '学生宿舍可以使用哪些电器，哪些属于违规电器？' }
]

const models = [
  { name: '现行制度查询', tag: '默认模式', desc: '优先检索当前有效版本，适合查询正在执行的校园规定。', icon: Sparkles, prompt: '本科生最长修业年限一般不超过几年？' },
  { name: '历史版本对照', tag: '时间查询', desc: '支持旧版、当时有效版本以及修订前后差异对照。', icon: BrainCircuit, prompt: '学生管理规定修订前后有哪些主要变化？' }
]

const faqs = [
  { q: '回答依据什么资料？', a: '当前主要依据《陕西师范大学学生手册》及其相关管理规定，回答会展示文件、版本、页码和章节来源。' },
  { q: '可以查询旧版规定吗？', a: '可以。系统区分现行、历史和截至日期语义，明确询问旧版或“截至某日期”时会按时间范围检索。' },
  { q: '游客对话会被保存吗？', a: '游客会话只用于当前浏览器会话和短期记忆，不写入正式用户会话历史；登录用户的会话由业务系统保存。' },
  { q: '支持哪些校园事务？', a: '当前覆盖学籍培养、考试成绩、奖助评优、处分管理、宿舍生活等学生手册高频事项。' }
]

function goToCampusQuestion(prompt) {
  router.push({ path: '/chat', query: { q: prompt } })
}

function scrollToSection(target) {
  document.getElementById(target)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
}

function showToast(message) {
  toast.value = message
  window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    toast.value = ''
  }, 2200)
}

function goToAuth() {
  router.push('/auth')
}

function onScroll() {
  scrolled.value = window.scrollY > 8
}

onMounted(() => {
  window.addEventListener('scroll', onScroll, { passive: true })
  onScroll()
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <div class="landing">
    <header class="site-nav" :class="{ 'nav-scrolled': scrolled }">
      <div class="nav-inner">
        <a class="nav-brand" href="#hero" @click.prevent="scrollToSection('hero')">
          <span class="brand-mark"><Sparkles :size="17" /></span>
          <span>校园 AI 咨询助手</span>
        </a>
        <div class="nav-actions">
          <button class="nav-login" @click="goToAuth">登录</button>
        </div>
      </div>
    </header>

    <section id="hero" class="hero">
      <HeroStarfield />
      <div class="hero-layout">
        <div class="hero-content">
          <span class="hero-badge"><Rocket :size="14" />学生手册知识库 · 校园事务智能咨询</span>
          <h1>校园 AI 咨询助手</h1>
          <p class="hero-tagline">学生手册里的问题，直接问</p>
          <p class="hero-desc">
            围绕学籍、考试、奖助、处分和校园生活提供有依据的回答，并保留文件、版本、页码和章节来源。
          </p>
          <div class="hero-actions">
            <RouterLink class="action-card action-primary" to="/chat">
              <span class="action-icon"><Send :size="18" /></span>
              <span class="action-copy">
                <strong>开始对话</strong>
                <small>咨询学籍、考试、奖助与校园生活</small>
              </span>
            </RouterLink>
            <button class="action-card action-secondary" type="button" @click="scrollToSection('use-cases')">
              <span class="action-icon"><BookOpen :size="18" /></span>
              <span class="action-copy">
                <strong>常见咨询</strong>
                <small>查看校园高频问题入口</small>
              </span>
            </button>
          </div>
        </div>
        <button class="learn-card" type="button" @click="scrollToSection('features')">
          <span class="learn-icon"><BookOpen :size="22" /></span>
          <span class="learn-title">
            <h2>咨询指南</h2>
            <ArrowUpRight class="learn-arrow" :size="18" />
          </span>
          <p>了解系统能查询哪些校园事务、如何使用历史版本，以及回答来源如何核对。</p>
        </button>
      </div>
      <button class="scroll-hint" title="向下滚动" @click="scrollToSection('features')">
        <ChevronDown :size="20" />
      </button>
    </section>

    <section id="features" class="section features-section">
      <div class="section-inner">
        <div class="section-head">
          <span class="section-kicker">功能介绍</span>
          <h2>围绕校园事务，给出有依据的回答</h2>
          <p>不只回答结论，也展示对应制度和来源，减少四处翻手册的时间。</p>
        </div>
        <div class="feature-grid">
          <div v-for="feature in features" :key="feature.title" class="feature-card">
            <span class="feature-icon"><component :is="feature.icon" :size="20" /></span>
            <h3>{{ feature.title }}</h3>
            <p>{{ feature.desc }}</p>
          </div>
        </div>
      </div>
    </section>

    <section id="use-cases" class="section scenarios-section">
      <div class="section-inner">
        <div class="section-head">
          <span class="section-kicker">使用场景</span>
          <h2>从最常遇到的校园问题开始</h2>
          <p>选择场景后会带着示例问题进入对话，也可以直接输入你自己的问题。</p>
        </div>
        <div class="scenario-grid">
          <button
            v-for="scenario in scenarios"
            :key="scenario.title"
            class="scenario-card"
            @click="goToCampusQuestion(scenario.prompt)"
          >
            <span class="scenario-icon"><component :is="scenario.icon" :size="20" /></span>
            <h3>{{ scenario.title }}</h3>
            <p>{{ scenario.desc }}</p>
            <span class="scenario-action">
              开始咨询
              <ArrowUpRight :size="15" />
            </span>
          </button>
        </div>
      </div>
    </section>

    <section id="models" class="section models-section">
      <div class="section-inner">
        <div class="section-head">
          <span class="section-kicker">咨询范围</span>
          <h2>先问现行制度，再查历史版本</h2>
          <p>默认只使用当前有效版本，明确询问旧版或截至日期时再扩大检索范围。</p>
        </div>
        <div class="model-grid">
          <div v-for="model in models" :key="model.name" class="model-card">
            <div class="model-top">
              <span class="model-icon"><component :is="model.icon" :size="20" /></span>
              <span class="model-tag">{{ model.tag }}</span>
            </div>
            <h3>{{ model.name }}</h3>
            <p>{{ model.desc }}</p>
            <button class="model-link" @click="goToCampusQuestion(model.prompt)">
              立即体验
              <ArrowUpRight :size="15" />
            </button>
          </div>
        </div>
      </div>
    </section>

    <section id="faq" class="section faq-section">
      <div class="section-inner">
        <div class="section-head">
          <span class="section-kicker">常见问题</span>
          <h2>你可能会关心</h2>
        </div>
        <div class="faq-list">
          <details v-for="(faq, index) in faqs" :key="index" class="faq-item">
            <summary>
              {{ faq.q }}
              <ChevronDown :size="18" />
            </summary>
            <p>{{ faq.a }}</p>
          </details>
        </div>
      </div>
    </section>

    <footer class="site-footer">
      <div class="footer-inner">
        <div class="footer-brand">
          <span class="brand-mark"><Sparkles :size="16" /></span>
          <strong>校园 AI 咨询助手</strong>
          <p>基于学生手册的校园事务智能问答演示。</p>
        </div>
        <div class="footer-cols">
          <div class="footer-col">
            <h4>产品</h4>
            <RouterLink to="/chat">开始咨询</RouterLink>
            <button @click="scrollToSection('use-cases')">常见问题</button>
            <button @click="goToCampusQuestion('学生管理规定修订前后有哪些主要变化？')">历史版本查询</button>
          </div>
          <div class="footer-col">
            <h4>能力</h4>
            <button @click="goToCampusQuestion('本科生最长修业年限一般不超过几年？')">现行制度</button>
            <button @click="goToCampusQuestion('学生管理规定修订前后有哪些主要变化？')">历史版本</button>
            <button @click="showToast('更新日志待接入')">更新日志</button>
          </div>
          <div class="footer-col">
            <h4>法务</h4>
            <button @click="showToast('隐私政策待接入')">隐私政策</button>
            <button @click="showToast('服务条款待接入')">服务条款</button>
            <button @click="showToast('反馈安全漏洞待接入')">安全反馈</button>
          </div>
        </div>
      </div>
      <div class="footer-bottom">
        <p>© 2026 校园 AI 咨询助手演示版</p>
      </div>
    </footer>

    <transition name="toast">
      <div v-if="toast" class="home-toast">{{ toast }}</div>
    </transition>
  </div>
</template>

<style scoped>
.landing {
  min-height: 100dvh;
  background: #ffffff;
  color: #38292c;
  overflow-x: hidden;
}

.site-nav {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  z-index: 50;
  background: rgba(255, 255, 255, 0);
  border-bottom: 1px solid transparent;
  transition: background 0.2s ease, border-color 0.2s ease;
}

.site-nav.nav-scrolled {
  background: rgba(255, 255, 255, 0.88);
  border-bottom-color: #f2d9dc;
  backdrop-filter: blur(14px);
}

.nav-inner {
  max-width: 1180px;
  margin: 0 auto;
  height: 64px;
  display: flex;
  align-items: center;
  padding: 0 24px;
}

.brand-mark {
  display: inline-flex;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #a11d2e;
  color: #fff;
}

.nav-brand {
  display: flex;
  align-items: center;
  gap: 9px;
  color: #38292c;
  font-size: 15px;
  font-weight: 700;
  text-decoration: none;
}

.nav-actions {
  margin-left: auto;
}

.nav-login {
  padding: 7px 18px;
  border: 1px solid #e7aeb6;
  border-radius: 8px;
  color: #8f1a28;
  font-size: 13px;
  font-weight: 600;
}

.nav-login:hover {
  background: #fbecee;
  border-color: #a11d2e;
}

.hero {
  position: relative;
  min-height: 100dvh;
  display: flex;
  align-items: center;
  padding: 120px 24px 80px;
  background: #ffffff;
  overflow: hidden;
}

.hero-layout {
  position: relative;
  z-index: 2;
  width: 100%;
  max-width: 1120px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 32px;
  align-items: center;
}

.hero-content {
  width: 100%;
  max-width: 660px;
}

.hero-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 6px 12px;
  border: 1px solid #e7c2c8;
  border-radius: 999px;
  background: #fbecee;
  color: #8f1a28;
  font-size: 13px;
  margin-bottom: 26px;
}

.hero h1 {
  font-size: 64px;
  line-height: 1.08;
  font-weight: 800;
  letter-spacing: 0;
  color: #801724;
}

.hero-tagline {
  margin-top: 18px;
  font-size: 25px;
  line-height: 1.4;
  color: #6b232d;
  font-weight: 600;
}

.hero-desc {
  margin-top: 14px;
  max-width: 620px;
  color: #8a6d72;
  font-size: 16px;
  line-height: 1.8;
}

.hero-actions {
  margin-top: 34px;
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.action-card {
  display: flex;
  align-items: center;
  gap: 12px;
  text-align: left;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #e6c2c7;
  background: #ffffff;
  box-shadow: 0 6px 18px rgba(161, 29, 46, 0.06);
  text-decoration: none;
  transition: transform 0.15s ease, border-color 0.15s ease, box-shadow 0.15s ease;
}

.action-card:hover {
  transform: translateY(-2px);
  border-color: #a11d2e;
  box-shadow: 0 10px 24px rgba(161, 29, 46, 0.12);
}

.action-primary {
  background: #a11d2e;
  border-color: #a11d2e;
  color: #ffffff;
}

.action-primary:hover {
  background: #8f1a28;
  border-color: #8f1a28;
}

.action-secondary {
  color: #38292c;
}

.action-icon {
  display: flex;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #8f1a28;
}

.action-primary .action-icon {
  background: rgba(255, 255, 255, 0.18);
  color: #ffffff;
}

.action-copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.action-copy strong {
  font-size: 15px;
  font-weight: 600;
}

.action-copy small {
  font-size: 12px;
  opacity: 0.72;
  white-space: nowrap;
}

.learn-card {
  align-self: stretch;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 14px;
  min-height: 400px;
  padding: 36px;
  border-radius: 8px;
  background: #a11d2e;
  border: 1px solid #a11d2e;
  color: #ffffff;
  box-shadow: 0 14px 34px rgba(161, 29, 46, 0.22);
  text-align: left;
  width: 100%;
  transition: transform 0.15s ease, box-shadow 0.15s ease;
}

.learn-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 18px 40px rgba(128, 23, 36, 0.3);
}

.learn-icon {
  display: flex;
  width: 46px;
  height: 46px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.16);
  color: #ffffff;
}

.learn-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.learn-card h2 {
  font-size: 22px;
  font-weight: 700;
}

.learn-card p {
  color: #ffdfe3;
  font-size: 14px;
  line-height: 1.8;
}

.learn-arrow {
  flex: 0 0 auto;
  opacity: 0;
  transform: translate(-4px, 4px);
  transition: opacity 0.15s ease, transform 0.15s ease;
}

.learn-card:hover .learn-arrow {
  opacity: 1;
  transform: translate(0, 0);
}

.scroll-hint {
  position: absolute;
  left: 50%;
  bottom: 26px;
  transform: translateX(-50%);
  z-index: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 38px;
  height: 38px;
  border-radius: 50%;
  color: #c08a92;
  animation: float-down 2.2s infinite ease-in-out;
}

.scroll-hint:hover {
  color: #a11d2e;
}

@keyframes float-down {
  0%,
  100% {
    transform: translate(-50%, 0);
  }
  50% {
    transform: translate(-50%, 6px);
  }
}

.section {
  padding: 96px 0;
}

.features-section,
.models-section {
  background: #fbf2f3;
}

.section-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
}

.section-head {
  max-width: 680px;
  margin-bottom: 44px;
}

.section-kicker {
  display: inline-block;
  font-size: 13px;
  color: #a11d2e;
  margin-bottom: 12px;
}

.section-head h2 {
  font-size: 32px;
  line-height: 1.3;
  font-weight: 700;
  color: #38292c;
}

.section-head p {
  margin-top: 12px;
  color: #8a6d72;
  font-size: 15px;
  line-height: 1.7;
}

.feature-grid,
.scenario-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 14px;
}

.feature-card,
.scenario-card,
.model-card,
.faq-item {
  background: #ffffff;
  border: 1px solid #e9ccd1;
  border-radius: 8px;
}

.feature-card {
  padding: 22px;
}

.feature-icon {
  display: flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #8f1a28;
  margin-bottom: 16px;
}

.feature-card h3 {
  font-size: 16px;
  font-weight: 600;
  margin-bottom: 8px;
  color: #38292c;
}

.feature-card p,
.scenario-card p,
.model-card p {
  color: #8a6d72;
  font-size: 13.5px;
  line-height: 1.7;
}

.scenario-card {
  display: flex;
  flex-direction: column;
  gap: 10px;
  width: 100%;
  padding: 22px;
  text-decoration: none;
  color: inherit;
  text-align: left;
  transition: transform 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.scenario-card:hover {
  transform: translateY(-2px);
  border-color: #a11d2e;
  background: #fffafb;
}

.scenario-icon {
  display: flex;
  width: 40px;
  height: 40px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #8f1a28;
}

.scenario-card h3 {
  font-size: 16px;
  font-weight: 600;
  color: #38292c;
}

.scenario-card p {
  flex: 1;
}

.scenario-action {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #a11d2e;
  font-size: 13px;
  font-weight: 600;
}

.model-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 14px;
}

.model-card {
  padding: 28px;
}

.model-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 18px;
}

.model-icon {
  display: flex;
  width: 42px;
  height: 42px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: #fbecee;
  color: #8f1a28;
}

.model-tag {
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid #e6c2c7;
  background: #fbecee;
  color: #8f1a28;
  font-size: 12px;
}

.model-card h3 {
  font-size: 22px;
  font-weight: 700;
  color: #38292c;
}

.model-card p {
  margin-top: 10px;
}

.model-link {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-top: 22px;
  color: #a11d2e;
  font-size: 14px;
  font-weight: 600;
  text-decoration: none;
}

.model-link:hover {
  color: #801724;
}

.faq-list {
  max-width: 760px;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.faq-item summary {
  list-style: none;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 16px 18px;
  cursor: pointer;
  font-size: 15px;
  font-weight: 600;
  color: #38292c;
}

.faq-item summary::-webkit-details-marker {
  display: none;
}

.faq-item summary svg {
  flex: 0 0 auto;
  color: #c08a92;
  transition: transform 0.2s ease;
}

.faq-item[open] summary svg {
  transform: rotate(180deg);
}

.faq-item p {
  padding: 0 18px 18px;
  color: #8a6d72;
  font-size: 14px;
  line-height: 1.8;
}

.site-footer {
  background: #7c1622;
  padding: 56px 0 0;
}

.footer-inner {
  max-width: 1120px;
  margin: 0 auto;
  padding: 0 24px;
  display: flex;
  gap: 48px;
  flex-wrap: wrap;
}

.footer-brand {
  flex: 1;
  min-width: 220px;
}

.footer-brand .brand-mark {
  background: rgba(255, 255, 255, 0.16);
}

.footer-brand strong {
  display: block;
  margin-top: 12px;
  font-size: 16px;
  color: #ffffff;
}

.footer-brand p {
  margin-top: 8px;
  color: #ffd4d9;
  font-size: 13px;
  line-height: 1.7;
}

.footer-cols {
  display: flex;
  gap: 64px;
  flex-wrap: wrap;
}

.footer-col {
  display: flex;
  flex-direction: column;
  gap: 10px;
  min-width: 120px;
}

.footer-col h4 {
  margin-bottom: 6px;
  color: #ffb8c1;
  font-size: 13px;
  font-weight: 600;
}

.footer-col a,
.footer-col button {
  padding: 2px 0;
  color: #ffe1e5;
  font-size: 13px;
  text-align: left;
  text-decoration: none;
}

.footer-col a:hover,
.footer-col button:hover {
  color: #ffffff;
}

.footer-bottom {
  max-width: 1120px;
  margin: 48px auto 0;
  padding: 18px 24px;
  border-top: 1px solid rgba(255, 255, 255, 0.14);
  color: #ffc0c7;
  font-size: 12px;
}

.home-toast {
  position: fixed;
  top: 16px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 80;
  background: #7c1622;
  color: #ffffff;
  padding: 9px 16px;
  border-radius: 8px;
  font-size: 13px;
  box-shadow: 0 8px 24px rgba(120, 20, 32, 0.24);
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

@media (max-width: 1024px) {
  .feature-grid,
  .scenario-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 960px) {
  .hero-layout {
    grid-template-columns: 1fr;
    gap: 24px;
  }

  .learn-card {
    min-height: 220px;
  }
}

@media (max-width: 767px) {
  .hero {
    padding: 110px 18px 76px;
  }

  .hero h1 {
    font-size: 42px;
  }

  .hero-tagline {
    font-size: 21px;
  }

  .hero-desc {
    font-size: 15px;
  }

  .hero-actions {
    grid-template-columns: 1fr;
  }

  .action-copy small {
    white-space: normal;
  }

  .section {
    padding: 72px 0;
  }

  .section-head h2 {
    font-size: 26px;
  }

  .feature-grid,
  .scenario-grid,
  .model-grid {
    grid-template-columns: 1fr;
  }

  .footer-cols {
    gap: 32px;
  }
}
</style>
