<script setup lang="ts">
import { useRoute } from 'vue-router'

defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'navigate'): void }>()
const route = useRoute()

const icons = {
  overview: 'M5.5 4.5h13a2 2 0 0 1 2 2v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2v-11a2 2 0 0 1 2-2Z M13.5 4.5v15 M16.5 8.5h1m-1 3.5h1m-1 3.5h1 M6.5 14.5l2-3 1.5 1 1-3',
  replay: 'M4 5.5v5h5 M4.2 10.5a8 8 0 1 1 1.3 6.2 M12 8v4l2.8 1.8',
  analysis: 'M4 4v16h16 M8 16v-4m4 4V8m4 8v-6m4 6V5',
  prediction: 'M3.5 18.5l5.2-5.2 3.7 2.1 2-2 M16.3 11.5l.9-.9m1.8-1.8 2-2 M17 6.8h4v4',
  evidence: 'M10 20H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h8l4 4v2m-4-6v4h4 M7.5 12h4m-4 4h2 M19.5 16a3.5 3.5 0 1 1-7 0 3.5 3.5 0 0 1 7 0Zm-1 2.5L21 21',
  data: 'M19 6c0 1.65-3.13 3-7 3s-7-1.35-7-3 3.13-3 7-3 7 1.35 7 3Z M5 6v12c0 1.65 3.13 3 7 3s7-1.35 7-3V6 M5 12c0 1.65 3.13 3 7 3s7-1.35 7-3',
}

interface NavChild {
  to: string
  name: string
  label: string
  tone?: 'attn' | 'obs' | 'accent' | 'danger'
}

interface NavItem {
  to: string
  name: keyof typeof icons
  label: string
  children: NavChild[]
}

const items: NavItem[] = [
  { to: '/overview', name: 'overview', label: '事件总览', children: [{ to: '/overview/impact', name: 'impact', label: '影响事件与行动' }] },
  { to: '/replay', name: 'replay', label: '历史回放', children: [] },
  {
    to: '/analysis/physical',
    name: 'analysis',
    label: '分析中心',
    children: [
      { to: '/analysis/physical', name: 'analysis', label: '物理', tone: 'attn' },
      { to: '/analysis/social', name: 'analysis', label: '社会', tone: 'obs' },
      { to: '/analysis/org', name: 'analysis', label: '组织', tone: 'accent' },
      { to: '/analysis/coupling', name: 'analysis', label: '耦合', tone: 'danger' },
    ],
  },
  { to: '/prediction', name: 'prediction', label: '预测中心', children: [] },
  { to: '/evidence', name: 'evidence', label: '异常与证据', children: [] },
  { to: '/data', name: 'data', label: '数据管理', children: [{ to: '/data/glossary', name: 'glossary', label: '资料与口径' }] },
]

function active(name: string, children: Array<{ name: string }>) {
  return route.name === name || children.some((c) => c.name === route.name)
}

function childActive(to: string) {
  return route.path === to
}
</script>

<template>
  <nav id="main-navigation" class="side" :class="{ open }" aria-label="主导航">
    <ul>
      <li v-for="item in items" :key="item.to">
        <RouterLink
          :to="item.to"
          class="link"
          :class="{ on: active(item.name, item.children) }"
          :aria-current="route.name === item.name && !item.children.some((c) => childActive(c.to)) ? 'page' : 'false'"
          @click="emit('navigate')"
        >
          <svg
            class="icon"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            stroke-width="1.6"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
            focusable="false"
          >
            <path :d="icons[item.name]" />
          </svg>
          {{ item.label }}
        </RouterLink>
        <ul v-if="item.children.length && active(item.name, item.children)" class="sub">
          <li v-for="c in item.children" :key="c.to">
            <RouterLink :to="c.to" class="sublink" :class="{ on: childActive(c.to) }" :aria-current="childActive(c.to) ? 'page' : undefined" @click="emit('navigate')">
              <span v-if="c.tone" class="subdot" :class="c.tone" aria-hidden="true"></span>
              <span>{{ c.label }}</span>
            </RouterLink>
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
  padding: 20px 12px 12px;
  background: var(--shell-deep);
  border-right: 1px solid var(--shell-line);
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
  padding: 9px 10px;
  margin-bottom: 4px;
  border-radius: var(--control-radius);
  color: var(--shell-muted);
  font-weight: 550;
  text-decoration: none;
  transition: background-color 0.15s ease, color 0.15s ease, box-shadow 0.15s ease;
}
.link:hover {
  background: var(--shell-surface);
  color: var(--shell-text);
  text-decoration: none;
}
.link.on {
  background: var(--control-selected);
  color: var(--shell-text);
  box-shadow: inset 2px 0 0 var(--line-active);
}
.icon {
  flex: none;
  width: 20px;
  height: 20px;
  color: var(--faint);
  transition: color 0.15s ease;
}
.link:hover .icon,
.link:focus-visible .icon,
.link.on .icon {
  color: var(--shell-highlight);
}
.sub {
  margin: 2px 0 10px 21px;
}
.sublink {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 5px 12px;
  border-left: 1px solid var(--shell-line);
  color: var(--shell-muted);
  font-size: 13px;
  text-decoration: none;
  transition: color 0.15s ease, border-color 0.15s ease;
}
.sublink:hover {
  color: var(--shell-text);
  text-decoration: none;
}
.sublink.on {
  color: var(--shell-highlight);
  border-left-color: var(--shell-highlight);
  font-weight: 550;
}
.subdot {
  width: 6px;
  height: 6px;
  border-radius: 2px;
  flex: none;
  opacity: 0.78;
}
.sublink.on .subdot {
  opacity: 1;
}
.subdot.attn { background: var(--attn); }
.subdot.obs { background: var(--obs); }
.subdot.accent { background: var(--accent); }
.subdot.danger { background: var(--danger); }
.side :focus-visible {
  outline-color: var(--shell-highlight);
}
.foot {
  margin-top: auto;
  margin-bottom: 0;
  padding: 12px 8px;
  border-top: 1px solid var(--shell-line);
  color: var(--shell-muted);
}
@media (max-width: 1100px) {
  .side {
    visibility: hidden;
    transform: translateX(-100%);
    transition: transform 0.18s ease;
    box-shadow: 4px 0 16px rgb(11 27 47 / 24%);
  }
  .side.open {
    visibility: visible;
    transform: none;
  }
}
@media (prefers-reduced-motion: reduce) {
  .side { transition: none; }
}
</style>
