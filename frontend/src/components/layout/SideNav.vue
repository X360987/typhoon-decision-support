<script setup lang="ts">
import { useRoute } from 'vue-router'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'navigate'): void }>()
const route = useRoute()

const items = [
  { to: '/overview', name: 'overview', label: '事件总览', icon: '⌂', children: [{ to: '/overview/impact', name: 'impact', label: '影响事件与行动' }] },
  { to: '/replay', name: 'replay', label: '历史回放', icon: '◷', children: [] },
  { to: '/analysis/social', name: 'analysis', label: '分析中心', icon: '▥', children: [] },
  { to: '/prediction', name: 'prediction', label: '预测中心', icon: '↗', children: [] },
  { to: '/evidence', name: 'evidence', label: '异常与证据', icon: '△', children: [] },
  { to: '/data', name: 'data', label: '数据管理', icon: '☰', children: [{ to: '/data/glossary', name: 'glossary', label: '资料与口径' }] },
]

function active(name: string, children: Array<{ name: string }>) {
  return route.name === name || children.some((c) => c.name === route.name)
}
</script>

<template>
  <nav class="side" :class="{ open }" aria-label="主导航">
    <ul>
      <li v-for="item in items" :key="item.to">
        <RouterLink
          :to="item.to"
          class="link"
          :class="{ on: active(item.name, item.children) }"
          :aria-current="active(item.name, item.children) ? 'page' : undefined"
          @click="emit('navigate')"
        >
          <span class="icon" aria-hidden="true">{{ item.icon }}</span>{{ item.label }}
        </RouterLink>
        <ul v-if="item.children.length && active(item.name, item.children)" class="sub">
          <li v-for="c in item.children" :key="c.to">
            <RouterLink :to="c.to" class="sublink" :class="{ on: route.name === c.name }" @click="emit('navigate')">{{ c.label }}</RouterLink>
          </li>
        </ul>
      </li>
    </ul>
    <p class="foot muted small">平台只提供观察与核验辅助，不自动发布公告、执行调度或认定责任。</p>
  </nav>
</template>

<style scoped>
.side {
  position: fixed;
  top: var(--top-h);
  bottom: 0;
  left: 0;
  width: var(--nav-w);
  display: flex;
  flex-direction: column;
  padding: 14px 10px;
  background: #fff;
  border-right: 1px solid var(--line);
  z-index: 900;
  overflow-y: auto;
}
ul {
  list-style: none;
  margin: 0;
  padding: 0;
}
.link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  margin-bottom: 2px;
  border-radius: 6px;
  color: #334155;
  font-weight: 550;
  text-decoration: none;
}
.link:hover {
  background: #f3f6fa;
  text-decoration: none;
}
.link.on {
  background: var(--accent-soft);
  color: var(--accent);
  box-shadow: inset 3px 0 0 var(--accent);
}
.icon {
  width: 18px;
  text-align: center;
}
.sub {
  margin: 0 0 6px 28px;
}
.sublink {
  display: block;
  padding: 5px 10px;
  border-left: 1px solid var(--line);
  color: var(--muted);
  font-size: 13px;
}
.sublink.on {
  color: var(--accent);
  border-left-color: var(--accent);
}
.foot {
  margin-top: auto;
  padding: 8px;
}
@media (max-width: 1100px) {
  .side {
    transform: translateX(-100%);
    transition: transform 0.18s ease;
    box-shadow: 4px 0 16px rgba(16, 42, 67, 0.08);
  }
  .side.open {
    transform: none;
  }
}
</style>
