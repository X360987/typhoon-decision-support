<script setup lang="ts">
import type { LoadStatus } from '../composables/useLoader'

const props = withDefaults(
  defineProps<{
    status: LoadStatus
    error?: string
    stale?: boolean
    empty?: boolean
    emptyText?: string
    loadingText?: string
  }>(),
  { error: '', stale: false, empty: false, emptyText: '当前条件下没有数据。', loadingText: '加载中…' },
)
const emit = defineEmits<{ (e: 'retry'): void }>()
</script>

<template>
  <div class="status-note" aria-live="polite">
    <p v-if="props.status === 'error'" class="note bad">
      加载失败：{{ props.error }}
      <button type="button" class="btn ghost" @click="emit('retry')">重试</button>
      <span v-if="props.stale">（下方为上一次成功加载的结果，可能已过期）</span>
    </p>
    <p v-else-if="props.status === 'loading' && props.stale" class="note info">正在按新条件刷新，下方暂为上一条件的结果。</p>
    <p v-else-if="props.status === 'loading'" class="muted small">{{ props.loadingText }}</p>
    <p v-else-if="props.status === 'ready' && props.empty" class="note">{{ props.emptyText }}</p>
  </div>
</template>

<style scoped>
.status-note:empty {
  display: none;
}
.status-note p {
  margin: 4px 0 8px;
}
</style>
