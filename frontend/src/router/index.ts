import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

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
  {
    path: '/analysis/:tab(social|org|physical|coupling)?',
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

export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.afterEach((to) => {
  document.title = `${String(to.meta.title || '')} · 台风灾害分析平台`
})
