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

defineProps<{ items: MetricCardView[] }>()

function qualityText(card: SummaryCard | undefined) {
  if (!card) return '无此指标'
  if (card.quality === 'strict_unavailable') return '到达时间未知，当时已知模式下不可用'
  if (card.quality === 'insufficient') return '该小时缺测（不等于 0）'
  return card.aggregation || ''
}
</script>

<template>
  <dl class="metric-row">
    <div v-for="item in items" :key="item.key" class="metric">
      <dt>{{ item.label }}</dt>
      <dd>
        <span class="value num" :class="item.tone">{{ fmtNum(item.card?.value, item.digits ?? 0) }}</span>
        <span v-if="item.card?.unit" class="unit">{{ item.card.unit }}</span>
      </dd>
      <dd class="meta">
        <span :class="{ warn: item.card?.quality !== 'ok' }">{{ qualityText(item.card) }}</span>
        <span v-if="item.card?.sample_size != null && item.card.quality === 'ok'"> · 样本 {{ item.card.sample_size }}</span>
      </dd>
    </div>
  </dl>
</template>

<style scoped>
.metric-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  margin: 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
}
.metric {
  padding: 12px 18px;
  border-right: 1px solid var(--line);
}
.metric:last-child {
  border-right: 0;
}
dt {
  color: var(--muted);
  font-size: 13px;
}
dd {
  margin: 0;
}
.value {
  font-size: 28px;
  font-weight: 700;
  line-height: 1.25;
}
.value.obs {
  color: var(--obs);
}
.value.accent {
  color: var(--accent);
}
.value.attn {
  color: var(--attn);
}
.unit {
  margin-left: 4px;
  color: var(--muted);
  font-size: 12px;
}
.meta {
  color: var(--faint);
  font-size: 12px;
}
.meta .warn {
  color: #a95d12;
}
</style>
