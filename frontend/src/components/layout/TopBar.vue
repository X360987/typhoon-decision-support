<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '../../api/client'
import { useLoader } from '../../composables/useLoader'
import { fmtTime, provinceName } from '../../lib/format'
import { useContextStore } from '../../stores/context'

defineProps<{ navOpen: boolean }>()
const emit = defineEmits<{ (e: 'toggle-nav'): void }>()
const platformMark = `${import.meta.env.BASE_URL}favicon.svg`
const ctx = useContextStore()
const { events, datasets, eventId, datasetId, province, replayMode, cursor, dataMode, ready } = storeToRefs(ctx)

const coverage = useLoader(
  (signal) => api.coverage({ dataset_id: ctx.datasetId, event_id: ctx.eventId }, signal),
  () => ctx.scopeKey,
  { enabled: () => ctx.ready && !ctx.dailyStats },
)
const provinces = computed(() =>
  Object.keys(coverage.data.value?.metric_matrix || {})
    .filter((p) => p !== 'ALL')
    .sort(),
)

function onEvent(e: Event) {
  ctx.selectEvent(Number((e.target as HTMLSelectElement).value))
}
function onDataset(e: Event) {
  void ctx.selectDataset((e.target as HTMLSelectElement).value)
}
</script>

<template>
  <header class="top">
    <div class="brand">
      <button type="button" class="btn menu" aria-label="展开或收起导航" aria-controls="main-navigation" :aria-expanded="navOpen" @click="emit('toggle-nav')">☰</button>
      <img class="logo" :src="platformMark" width="29" height="29" alt="" />
      <span class="name">台风灾害分析平台</span>
    </div>
    <div class="controls" :class="{ 'has-datasets': datasets.length > 1 }">
      <label v-if="datasets.length > 1" class="field">
        <span>数据集</span>
        <select class="input" :value="datasetId" @change="onDataset">
          <option v-for="d in datasets" :key="d.id" :value="d.id">{{ d.name }}</option>
        </select>
      </label>
      <label class="field">
        <span>台风事件</span>
        <select class="input" :value="eventId ?? ''" :disabled="!events.length" @change="onEvent">
          <option v-if="!events.length" value="">暂无事件</option>
          <option v-for="e in events" :key="e.id" :value="e.id">{{ e.name }}</option>
        </select>
      </label>
      <label v-if="!ctx.dailyStats" class="field">
        <span>省份</span>
        <select v-model="province" class="input" :disabled="!ready">
          <option value="">全部（全国去重）</option>
          <option v-for="p in provinces" :key="p" :value="p">{{ provinceName(p) }}</option>
        </select>
      </label>
      <div v-if="!ctx.dailyStats" class="seg" role="group" aria-label="回放模式">
        <button type="button" :class="{ on: replayMode === 'as_known' }" :aria-pressed="replayMode === 'as_known'" @click="replayMode = 'as_known'">
          当时已知
        </button>
        <button
          type="button"
          :class="{ on: replayMode === 'retrospective' }"
          :aria-pressed="replayMode === 'retrospective'"
          @click="replayMode = 'retrospective'"
        >
          事后复盘
        </button>
      </div>
    </div>
    <div class="status">
      <span class="tag" :class="dataMode ?? undefined" title="数据模式由服务端配置决定">
        {{ dataMode === 'real' ? '真实数据' : dataMode === 'demo' ? '模拟数据' : '未连接' }}
      </span>
      <span v-if="ctx.dailyStats" class="clock">全国 · 按日统计</span>
      <span v-else class="clock num" title="分析时刻（北京时间）。当时已知模式下，所有页面只使用此刻之前已到达的数据。">
        北京时间 {{ fmtTime(cursor) }}
      </span>
    </div>
  </header>
</template>

<style scoped>
.top {
  position: fixed;
  inset: 0 0 auto 0;
  height: var(--top-h);
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 0 22px 0 0;
  background: var(--shell);
  backdrop-filter: blur(var(--hud-blur));
  -webkit-backdrop-filter: blur(var(--hud-blur));
  color: var(--shell-text);
  border-bottom: 1px solid var(--shell-line);
  z-index: 1000;
}
.brand {
  width: var(--nav-w);
  flex: none;
  display: flex;
  align-items: center;
  gap: 10px;
  padding-left: 18px;
  font-weight: 650;
  font-size: 15px;
  letter-spacing: -0.01em;
}
.logo {
  display: block;
  flex: none;
  padding: 4px;
  border-radius: 8px;
  background: var(--accent-soft);
  border: 1px solid color-mix(in oklab, var(--accent) 30%, transparent);
}
.menu {
  display: none;
  place-items: center;
  padding: 0;
  width: 34px;
  height: 34px;
  flex: none;
  font-size: 18px;
}
.controls {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  overflow-x: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--shell-line) transparent;
}
.controls select {
  max-width: 220px;
  color: var(--shell-text);
  color-scheme: dark;
  background: var(--control-bg);
  border-color: var(--line);
}
.controls select:hover:not(:disabled) {
  border-color: var(--line-strong);
  background: var(--control-hover);
}
.controls select:focus-visible {
  outline-offset: -3px;
}
.controls .field > span {
  color: var(--faint);
  font-size: 12px;
}
.controls .seg {
  flex: none;
}
.controls .seg button {
  padding-inline: 11px;
  font-size: 13px;
}
.top :focus-visible {
  outline-color: var(--shell-highlight);
}
.status {
  display: flex;
  align-items: center;
  flex: none;
  gap: 10px;
}
.status .tag {
  background: var(--shell-surface);
  color: var(--shell-muted);
  border-color: var(--shell-line);
}
.status .tag::before {
  content: '';
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: currentColor;
}
.status .tag.demo {
  background: var(--attn-soft);
  border-color: color-mix(in oklab, var(--attn) 34%, transparent);
  color: var(--attn);
}
.status .tag.real {
  background: var(--obs-soft);
  border-color: color-mix(in oklab, var(--obs) 34%, transparent);
  color: var(--obs);
}
.clock {
  white-space: nowrap;
  padding: 4px 10px;
  border-radius: var(--control-radius);
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text-secondary);
  font-size: 12px;
  font-family: var(--font-mono);
}
@media (max-width: 1100px) {
  .menu {
    display: grid;
  }
  .brand {
    width: auto;
  }
}
@media (max-width: 760px) {
  .top {
    display: grid;
    grid-template-areas: "brand status" "controls controls";
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-rows: 44px 79px;
    gap: 0 8px;
    padding: 4px 12px 9px;
  }
  .brand {
    grid-area: brand;
    padding: 0;
    gap: 7px;
    font-size: 14px;
  }
  .brand .logo {
    display: none;
  }
  .controls {
    grid-area: controls;
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    grid-template-rows: repeat(2, 1fr);
    height: 100%;
    gap: 4px 8px;
    padding-top: 4px;
    border-top: 1px solid var(--shell-line);
    overflow: visible;
  }
  .controls.has-datasets {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
  .controls select {
    width: 100%;
    min-width: 0;
    max-width: none;
    font-size: 12px;
  }
  .controls .field > span {
    position: absolute;
    width: 1px;
    height: 1px;
    overflow: hidden;
    clip-path: inset(50%);
  }
  .controls .seg {
    grid-column: 1 / -1;
  }
  .controls .seg button {
    flex: 1;
    min-height: 28px;
    font-size: 12px;
  }
  .status {
    grid-area: status;
    flex-direction: column;
    align-items: flex-end;
    gap: 0;
  }
  .status .tag,
  .clock {
    font-size: 10px;
  }
  .status .tag {
    padding-block: 0;
  }
}
</style>
