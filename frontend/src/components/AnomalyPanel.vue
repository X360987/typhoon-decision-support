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
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
}
.item {
  position: relative;
  display: grid;
  gap: 3px;
  width: 100%;
  padding: 10px 12px 10px 24px;
  border: 1px solid var(--line);
  border-radius: calc(var(--panel-radius) - 3px);
  background: color-mix(in oklab, var(--surface-tint) 50%, var(--surface));
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
.item:hover .title {
  color: var(--accent-hover);
}
.item:hover {
  border-color: var(--line-strong);
  background: var(--surface-tint);
}
.dot {
  position: absolute;
  left: 10px;
  top: 15px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px color-mix(in oklab, var(--accent) 55%, transparent);
}
.dot.pair {
  background: var(--attn);
  box-shadow: 0 0 8px color-mix(in oklab, var(--attn) 55%, transparent);
}
.dot.joint {
  background: var(--danger);
  box-shadow: 0 0 8px color-mix(in oklab, var(--danger) 55%, transparent);
}
.time {
  color: var(--faint);
  font-family: var(--font-mono);
  font-size: 11.5px;
}
.title {
  color: var(--text);
  font-size: 13.5px;
  font-weight: 600;
  transition: color 0.15s ease;
}
.desc {
  color: var(--muted);
  font-size: 12.5px;
  line-height: 1.48;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.meta {
  color: var(--faint);
  font-size: 11.5px;
}
</style>
