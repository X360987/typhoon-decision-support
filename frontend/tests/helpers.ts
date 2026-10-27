import { flushPromises } from '@vue/test-utils'
import { createPinia, setActivePinia, type Pinia } from 'pinia'
import { createMemoryHistory, createRouter, type Router } from 'vue-router'
import type { EventItem } from '../src/api/types'
import { useContextStore } from '../src/stores/context'

export const EVENT: EventItem = {
  id: 1,
  dataset_id: 'demo',
  event_code: 'SIM-A',
  name: '模拟台风A',
  external_typhoon_id: null,
  start_time: '2023-07-26T00:00:00',
  end_time: '2023-07-28T23:00:00',
  status: 'closed',
  config_version: 'v1',
  active_version: 'r1',
}

export const EVENT_B: EventItem = { ...EVENT, id: 2, event_code: 'SIM-B', name: '模拟台风B', start_time: '2023-09-04T00:00:00', end_time: '2023-09-06T23:00:00' }

export const CURSOR = '2023-07-28T11:00:00'

export function setup(path = '/'): { pinia: Pinia; router: Router; ctx: ReturnType<typeof useContextStore> } {
  const pinia = createPinia()
  setActivePinia(pinia)
  const ctx = useContextStore()
  ctx.health = { status: 'ok', database: true, error: null, data_mode: 'demo', write_requires_key: false, seed_allowed: true, time: '' }
  ctx.datasets = [{ id: 'demo', name: '模拟', data_mode: 'demo', description: null }]
  ctx.events = [EVENT, EVENT_B]
  ctx.datasetId = 'demo'
  ctx.eventId = 1
  ctx.cursor = CURSOR
  ctx.bootStatus = 'ready'
  const Blank = { template: '<div />' }
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/', component: Blank },
      { path: '/overview', name: 'overview', component: Blank },
      { path: '/replay', name: 'replay', component: Blank },
      { path: '/prediction', name: 'prediction', component: Blank },
      { path: '/evidence/:id(\\d+)?', name: 'evidence', component: Blank },
      { path: '/data', name: 'data', component: Blank },
      { path: '/data/glossary', name: 'glossary', component: Blank },
    ],
  })
  void router.push(path)
  return { pinia, router, ctx }
}

export async function settle(rounds = 4) {
  for (let i = 0; i < rounds; i++) await flushPromises()
}
