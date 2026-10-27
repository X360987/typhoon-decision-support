<script setup lang="ts">
import { computed } from 'vue'
import { storeToRefs } from 'pinia'
import { api } from '../../api/client'
import { useLoader } from '../../composables/useLoader'
import { fmtTime, provinceName } from '../../lib/format'
import { useContextStore } from '../../stores/context'

const emit = defineEmits<{ (e: 'toggle-nav'): void }>()
const ctx = useContextStore()
const { events, datasets, eventId, datasetId, province, replayMode, cursor, dataMode, ready } = storeToRefs(ctx)

const coverage = useLoader(
  (signal) => api.coverage({ dataset_id: ctx.datasetId, event_id: ctx.eventId }, signal),
  () => ctx.scopeKey,
  { enabled: () => ctx.ready },
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
      <button type="button" class="menu" aria-label="展开或收起导航" @click="emit('toggle-nav')">☰</button>
      <span class="logo" aria-hidden="true">◎</span>
      <span class="name">台风灾害分析平台</span>
    </div>
    <div class="controls">
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
      <label class="field">
        <span>省份</span>
        <select v-model="province" class="input" :disabled="!ready">
          <option value="">全部（全国去重）</option>
          <option v-for="p in provinces" :key="p" :value="p">{{ provinceName(p) }}</option>
        </select>
      </label>
      <div class="seg" role="group" aria-label="回放模式">
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
      <span class="tag" :class="dataMode === 'real' ? 'real' : 'demo'" :title="'数据模式由服务端配置决定'">
        {{ dataMode === 'real' ? '真实数据' : dataMode === 'demo' ? '模拟数据' : '未连接' }}
      </span>
      <span class="clock num" title="分析时刻（北京时间）。当时已知模式下，所有页面只使用此刻之前已到达的数据。">
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
  padding: 0 20px 0 0;
  background: #fff;
  border-bottom: 1px solid var(--line);
  z-index: 1000;
}
.brand {
  width: var(--nav-w);
  flex: none;
  display: flex;
  align-items: center;
  gap: 8px;
  padding-left: 18px;
  font-weight: 700;
  font-size: 16px;
}
.logo {
  color: var(--accent);
  font-size: 20px;
}
.menu {
  display: none;
  border: 0;
  background: none;
  font-size: 18px;
  cursor: pointer;
}
.controls {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 14px;
  min-width: 0;
  overflow-x: auto;
}
.controls select {
  max-width: 220px;
}
.clock {
  white-space: nowrap;
  color: #334155;
}
@media (max-width: 1100px) {
  .menu {
    display: inline-block;
  }
  .brand {
    width: auto;
  }
}
@media (max-width: 760px) {
  .name {
    display: none;
  }
  .controls {
    justify-content: flex-start;
    gap: 10px;
  }
  .controls .field > span {
    display: none;
  }
}
</style>
