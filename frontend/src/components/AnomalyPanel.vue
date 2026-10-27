<script setup lang="ts">
import type { Anomaly } from '../api/types'
import { dimensionNames, SCOPE_NAMES, anomalyName, fmtTime, provinceName } from '../lib/format'

defineProps<{
  items: Anomaly[]
  emptyText?: string
}>()
const emit = defineEmits<{ (e: 'open', id: number): void }>()
</script>

<template>
  <ol class="feed">
    <li v-for="a in items" :key="a.id">
      <button type="button" class="item" @click="emit('open', a.id)">
        <span class="dot" :class="a.analysis_scope" aria-hidden="true"></span>
        <span class="time num">{{ fmtTime(a.hour_bj) }} · {{ provinceName(a.province_code) }}</span>
        <span class="title">{{ anomalyName(a.anomaly_type) }}</span>
        <span class="desc">{{ a.explanation }}</span>
        <span class="meta">
          {{ SCOPE_NAMES[a.analysis_scope] }} · {{ dimensionNames(a.dimensions) }}
          <template v-if="a.quality_status !== 'ok'"> · 质量：{{ a.quality_status }}</template>
        </span>
      </button>
    </li>
    <li v-if="!items.length" class="muted small">{{ emptyText || '暂无待核查异常。' }}</li>
  </ol>
</template>

<style scoped>
.feed {
  list-style: none;
  margin: 0;
  padding: 0;
}
.feed li {
  border-bottom: 1px solid var(--line);
}
.item {
  position: relative;
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 12px 4px 12px 22px;
  border: 0;
  background: none;
  text-align: left;
  cursor: pointer;
}
.item:hover .title {
  color: var(--accent);
}
.dot {
  position: absolute;
  left: 4px;
  top: 18px;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--accent);
}
.dot.pair {
  background: var(--attn);
}
.dot.joint {
  background: var(--danger);
}
.time {
  color: var(--muted);
  font-size: 12px;
}
.title {
  font-weight: 600;
}
.desc {
  color: #475569;
  font-size: 13px;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  color: var(--faint);
  font-size: 12px;
}
</style>
