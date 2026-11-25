<script setup lang="ts">
import { useRoute } from 'vue-router'

defineProps<{ label: string; sections: Array<{ id: string; label: string }>; pending?: boolean }>()
const route = useRoute()
</script>

<template>
  <nav class="section-nav" :aria-label="label" :data-sections-pending="pending || undefined">
    <RouterLink
      v-for="section in sections"
      :key="section.id"
      :to="{ path: route.path, query: route.query, hash: `#${section.id}` }"
      custom
      v-slot="{ href, navigate }"
    >
      <a
        :href="href"
        class="btn"
        :aria-current="route.hash === `#${section.id}` ? 'location' : undefined"
        @click="navigate"
      >{{ section.label }}</a>
    </RouterLink>
  </nav>
</template>

<style scoped>
.section-nav {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 16px;
}
.section-nav .btn {
  min-height: 30px;
  padding-inline: 12px;
  border-color: var(--line);
  border-radius: 999px;
  font-size: 12.5px;
  color: var(--muted);
}
.section-nav [aria-current='location'] {
  background: var(--control-selected);
  border-color: color-mix(in oklab, var(--accent) 42%, transparent);
  color: var(--control-selected-text);
}
</style>
