<script setup lang="ts">
import type { SummaryCard } from '../api/types'
import { fmtNum } from '../lib/format'

export interface MetricCardView {
  key: string
  label: string
  card: SummaryCard | undefined
  tone: 'obs' | 'accent' | 'attn'
  digits?: number
}

const props = defineProps<{ items: MetricCardView[]; daily?: boolean }>()

function qualityText(card: SummaryCard | undefined) {
  if (!card) return '无此指标'
  if (card.quality === 'strict_unavailable') return '到达时间未知，当时已知模式下不可用'
  if (card.quality === 'insufficient') return props.daily ? '所选时段缺测' : '该小时缺测（不等于 0）'
  if (card.aggregation === 'selected_range_count') return '时段累计'
  return card.aggregation || ''
}
</script>

<template>
  <dl class="metric-row">
    <div v-for="item in items" :key="item.key" class="metric" :class="item.tone">
      <dt>{{ item.label }}</dt>
      <dd>
        <span class="value num">{{ fmtNum(item.card?.value, item.digits ?? 0) }}</span>
        <span v-if="item.card?.unit" class="unit">{{ item.card.unit }}</span>
      </dd>
      <dd class="meta">
        <span :class="{ warn: item.card?.quality !== 'ok' }">{{ qualityText(item.card) }}</span>
        <span v-if="!daily && item.card?.sample_size != null && item.card.quality === 'ok'"> · 样本 {{ item.card.sample_size }}</span>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.metric-row {
  display: grid;
  gap: 8px;
  margin: 0;
}
.metric {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: baseline;
  gap: 3px 10px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--metric-color);
  border-radius: calc(var(--panel-radius) - 3px);
  background: color-mix(in oklab, var(--surface-tint) 65%, var(--surface));
  transition: border-color 0.15s ease, background-color 0.15s ease;
}
.metric:hover {
  border-color: var(--line-strong);
  border-left-color: var(--metric-color);
  background: var(--surface-tint);
}
dt {
  color: var(--text-secondary);
  font-size: 12.5px;
  font-weight: 600;
}
dd {
  margin: 0;
}
.value {
  color: var(--metric-color);
  font-family: var(--font-mono);
  font-size: 22px;
  font-weight: 650;
  line-height: 1.1;
  letter-spacing: -0.02em;
}
.metric.obs {
  --metric-color: var(--obs);
}
.metric.accent {
  --metric-color: var(--accent);
}
.metric.attn {
  --metric-color: var(--attn);
}
.unit {
  margin-left: 4px;
  color: var(--muted);
  font-size: 11.5px;
}
.meta {
  grid-column: 1 / -1;
  color: var(--faint);
  font-size: 11.5px;
}
.meta .warn {
  color: var(--attn);
}
</style>
