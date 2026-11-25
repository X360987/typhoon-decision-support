import { createRouter, createWebHashHistory, type RouteRecordRaw, type Router } from 'vue-router'

export const routes: RouteRecordRaw[] = [
  { path: '/', redirect: '/overview' },
  { path: '/overview', name: 'overview', component: () => import('../views/OverviewView.vue'), meta: { title: '事件总览' } },
  {
    path: '/overview/impact',
    name: 'impact',
    component: () => import('../views/ImpactView.vue'),
    meta: { title: '影响事件与行动', parent: 'overview' },
  },
  { path: '/replay', name: 'replay', component: () => import('../views/ReplayView.vue'), meta: { title: '历史回放' } },
  // 进入分析中心默认落到物理维度（数据质量最高），显式重定向保证侧栏子项能正确高亮
  { path: '/analysis', redirect: '/analysis/physical' },
  {
    path: '/analysis/:tab(social|org|physical|coupling)',
    name: 'analysis',
    component: () => import('../views/AnalysisView.vue'),
    meta: { title: '分析中心' },
  },
  { path: '/prediction', name: 'prediction', component: () => import('../views/PredictionView.vue'), meta: { title: '预测中心' } },
  { path: '/evidence/:id(\\d+)?', name: 'evidence', component: () => import('../views/EvidenceView.vue'), meta: { title: '异常与证据' } },
  { path: '/data', name: 'data', component: () => import('../views/DataView.vue'), meta: { title: '数据管理' } },
  {
    path: '/data/glossary',
    name: 'glossary',
    component: () => import('../views/GlossaryView.vue'),
    meta: { title: '资料与口径', parent: 'data' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/overview' },
]

function waitForSection(id: string): Promise<HTMLElement | null> {
  function readySection() {
    const section = document.getElementById(id)
    return section?.closest('.page')?.querySelector('[data-sections-pending="true"]') ? null : section
  }

  const section = readySection()
  const main = document.getElementById('main')
  if (section || !main) return Promise.resolve(section)

  return new Promise((resolve) => {
    const observer = new MutationObserver(() => {
      const target = readySection()
      if (target) finish(target)
    })
    const timeout = window.setTimeout(() => finish(document.getElementById(id)), 3000)
    function finish(target: HTMLElement | null) {
      observer.disconnect()
      window.clearTimeout(timeout)
      resolve(target)
    }
    observer.observe(main, { childList: true, subtree: true, attributes: true, attributeFilter: ['data-sections-pending'] })
  })
}

export const router: Router = createRouter({
  history: createWebHashHistory(),
  routes,
  async scrollBehavior(to, from, savedPosition) {
    // The evidence view restores scroll and focus within its list/detail route.
    if (to.name === 'evidence' && from.name === 'evidence') return false
    if (savedPosition) return savedPosition
    if (to.hash) {
      const section = await waitForSection(to.hash.slice(1))
      if (router.currentRoute.value.fullPath !== to.fullPath) return false
      if (section) {
        section.focus({ preventScroll: true })
        const offset = parseFloat(getComputedStyle(document.documentElement).scrollPaddingTop)
        return { el: section, top: Number.isFinite(offset) ? offset : 0 }
      }
    }
    if (to.name === from.name) return false
    return { top: 0 }
  },
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '')} · 台风灾害分析平台`
})
