<script setup lang="ts">
import { onMounted, ref } from 'vue'
import SideNav from './components/layout/SideNav.vue'
import TopBar from './components/layout/TopBar.vue'
import { useContextStore } from './stores/context'

const ctx = useContextStore()
const navOpen = ref(false)

onMounted(() => {
  void ctx.bootstrap()
})
</script>

<template>
  <a class="skip" href="#main">跳到主要内容</a>
  <TopBar @toggle-nav="navOpen = !navOpen" />
  <SideNav :open="navOpen" @navigate="navOpen = false" />
  <div v-if="navOpen" class="scrim" aria-hidden="true" @click="navOpen = false"></div>
  <main id="main" class="main" tabindex="-1">
    <RouterView v-slot="{ Component }">
      <component :is="Component" />
    </RouterView>
  </main>
</template>

<style scoped>
.main {
  margin-left: var(--nav-w);
  padding-top: var(--top-h);
  min-height: 100vh;
}
.main:focus {
  outline: none;
}
.skip {
  position: absolute;
  left: -999px;
  top: 0;
  z-index: 2000;
  padding: 8px 12px;
  background: #fff;
}
.skip:focus {
  left: 8px;
}
.scrim {
  display: none;
}
@media (max-width: 1100px) {
  .main {
    margin-left: 0;
  }
  .scrim {
    display: block;
    position: fixed;
    inset: var(--top-h) 0 0 0;
    background: rgba(16, 42, 67, 0.2);
    z-index: 800;
  }
}
</style>
