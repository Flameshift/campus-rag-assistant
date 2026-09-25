<script setup>
import { ArrowUpRight, Compass, GraduationCap, HeartHandshake, Lightbulb, Sparkles } from '@lucide/vue'

const emit = defineEmits(['pick'])

const categories = [
  { title: '学籍与培养', desc: '注册、休复学、转专业与毕业要求', icon: GraduationCap, prompt: '本科生最长修业年限一般不超过几年？' },
  { title: '考试与成绩', desc: '补考、重修、成绩记载与考核纪律', icon: Compass, prompt: '专业必修课挂科后应该重修还是补考？' },
  { title: '奖助与评优', desc: '奖学金、助学金、评优条件和流程', icon: HeartHandshake, prompt: '申请国家励志奖学金通常需要满足哪些条件？' },
  { title: '宿舍与日常', desc: '宿舍用电、门禁、请假与日常管理', icon: Lightbulb, prompt: '学生宿舍可以使用哪些电器，哪些属于违规电器？' }
]

const quickPrompts = [
  '新生请假最多可以请多久？',
  '公共必修课不及格可以补考吗？',
  '本科生最长修业年限是多少年？',
  '奖学金评选一般看哪些方面？'
]
</script>

<template>
  <div class="welcome">
    <div class="welcome-inner">
      <div class="welcome-hero">
        <span class="welcome-mark"><Sparkles :size="22" /></span>
        <h1>今天想咨询哪件校园事务？</h1>
        <p>基于学生手册回答问题，并展示对应文件、版本、页码和章节来源</p>
      </div>
      <div class="suggestion-grid">
        <button
          v-for="category in categories"
          :key="category.title"
          class="suggestion-card"
          @click="emit('pick', category.prompt)"
        >
          <span class="card-icon"><component :is="category.icon" :size="18" /></span>
          <span class="card-copy">
            <strong>{{ category.title }}</strong>
            <span>{{ category.desc }}</span>
          </span>
          <ArrowUpRight class="card-arrow" :size="16" />
        </button>
      </div>
      <div class="quick-row">
        <button v-for="prompt in quickPrompts" :key="prompt" class="quick-chip" @click="emit('pick', prompt)">
          {{ prompt }}
        </button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.welcome {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  padding: 24px 20px 40px;
}

.welcome-inner {
  width: 100%;
  max-width: 760px;
}

.welcome-hero {
  text-align: center;
  margin-bottom: 28px;
}

.welcome-mark {
  display: inline-flex;
  width: 44px;
  height: 44px;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: var(--color-primary);
  color: #fff;
  margin-bottom: 16px;
  box-shadow: 0 8px 20px rgba(161, 29, 46, 0.22);
}

.welcome h1 {
  font-size: 32px;
  line-height: 1.25;
  font-weight: 700;
}

.welcome p {
  margin-top: 10px;
  color: var(--color-text-secondary);
  font-size: 15px;
}

.suggestion-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.suggestion-card {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 8px;
  text-align: left;
  transition: border-color 0.15s ease, box-shadow 0.15s ease, transform 0.15s ease;
}

.suggestion-card:hover {
  border-color: #e1bcc1;
  box-shadow: 0 4px 14px rgba(31, 35, 41, 0.06);
  transform: translateY(-1px);
}

.card-icon {
  display: flex;
  width: 38px;
  height: 38px;
  flex: 0 0 38px;
  align-items: center;
  justify-content: center;
  border-radius: 8px;
  background: var(--color-primary-soft);
  color: var(--color-primary);
}

.card-copy {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  flex: 1;
}

.card-copy strong {
  font-size: 14px;
  font-weight: 600;
}

.card-copy span {
  font-size: 12.5px;
  color: var(--color-text-secondary);
}

.card-arrow {
  flex: 0 0 auto;
  color: #c3c8d2;
  transition: color 0.15s ease;
}

.suggestion-card:hover .card-arrow {
  color: var(--color-primary);
}

.quick-row {
  display: flex;
  flex-wrap: wrap;
  justify-content: center;
  gap: 8px;
}

.quick-chip {
  padding: 7px 14px;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: 999px;
  color: var(--color-text-secondary);
  font-size: 13px;
  transition: color 0.15s ease, border-color 0.15s ease, background 0.15s ease;
}

.quick-chip:hover {
  color: var(--color-primary);
  border-color: #e1bcc1;
  background: var(--color-primary-soft);
}

@media (max-width: 767px) {
  .welcome {
    padding: 34px 14px 32px;
    align-items: flex-start;
  }

  .welcome h1 {
    font-size: 26px;
  }

  .welcome p {
    font-size: 14px;
  }

  .suggestion-grid {
    grid-template-columns: 1fr;
  }
}
</style>
