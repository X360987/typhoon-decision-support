<script setup lang="ts">
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
</script>

<template>
  <slot v-if="ctx.ready" />
  <div v-else class="gate" aria-live="polite">
    <p v-if="ctx.bootStatus === 'loading' || ctx.bootStatus === 'idle'" class="muted">正在连接服务并读取数据集…</p>
    <template v-else-if="ctx.bootStatus === 'error'">
      <p class="note bad">无法连接后端：{{ ctx.bootError }}</p>
      <button type="button" class="btn" @click="ctx.bootstrap()">重新连接</button>
    </template>
    <template v-else-if="ctx.bootStatus === 'no_dataset'">
      <p class="note">
        {{ ctx.dataMode === 'real' ? '真实模式下尚无数据集。平台不会用演示数据填充，请先在数据管理中登记事件并导入数据。' : '尚无数据集。可在数据管理中生成模拟数据或导入数据。' }}
      </p>
      <RouterLink class="btn" to="/data">前往数据管理</RouterLink>
    </template>
    <template v-else-if="ctx.bootStatus === 'no_event'">
      <p class="note">当前数据集还没有登记台风事件。</p>
      <RouterLink class="btn" to="/data">前往数据管理登记事件</RouterLink>
    </template>
  </div>
</template>

<style scoped>
.gate {
  display: grid;
  gap: 12px;
  justify-items: start;
  padding: 24px 0;
  max-width: 640px;
}
</style>
