<script setup lang="ts">
defineProps<{ pages: number; total: number; label?: string }>()
const page = defineModel<number>({ required: true })
</script>

<template>
  <div v-if="pages > 1" class="pager" role="navigation" :aria-label="label || '分页'">
    <button type="button" class="btn ghost" :disabled="page <= 1" @click="page -= 1">上一页</button>
    <span class="small num">第 {{ page }} / {{ pages }} 页 · 共 {{ total }} 条</span>
    <button type="button" class="btn ghost" :disabled="page >= pages" @click="page += 1">下一页</button>
  </div>
</template>

<style scoped>
.pager {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
  margin-top: 8px;
}
</style>
