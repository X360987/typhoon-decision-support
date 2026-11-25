import { mount } from '@vue/test-utils'
import { expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import type { RegistryMetric } from '../src/api/types'
import ProvinceMap from '../src/components/ProvinceMap.vue'
import TrendChart from '../src/components/TrendChart.vue'
import TopBar from '../src/components/layout/TopBar.vue'
import OverviewView from '../src/views/OverviewView.vue'
import { EVENT, EVENT_B, setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
vi.mock('../src/components/TrendChart.vue', () => ({
  default: { name: 'TrendChart', props: ['series'], template: '<div />' },
}))

it('uses national daily metrics with the integration backend and keeps missing counts distinct from zero', async () => {
  const { pinia, router, ctx } = setup('/overview')
  ctx.replayMode = 'as_known'
  ctx.province = 'FJ'
  const event = { ...EVENT, external_typhoon_id: '2305', name: '杜苏芮' }
  vi.mocked(api.health).mockResolvedValue({ ...ctx.health!, data_mode: 'real' })
  vi.mocked(api.datasets).mockResolvedValue({ data_mode: 'real', items: ctx.datasets })
  vi.mocked(api.events).mockResolvedValue({ items: [event] })
  const ids = ['weibo_count', 'government_weibo_count', 'non_government_weibo_count', 'unclassified_weibo_count', 'suspension_count']
  vi.mocked(api.registry).mockResolvedValue({
    rule_version: 'mvp-1', rules: {}, items: ids.map((id) => ({ id, aggregation: 'daily_count' }) as RegistryMetric),
  })
  vi.mocked(api.summary).mockResolvedValue({
    context: { start: '2023-07-26T00:00:00', end: '2023-07-28T23:00:00' } as never,
    data_mode: 'real', empty: false,
    cards: {
      weibo_count: { metric_id: 'weibo_count', value: 2, unit: '条', quality: 'ok', aggregation: 'selected_range_count' } as never,
      government_weibo_count: { metric_id: 'government_weibo_count', value: null, unit: '条', quality: 'insufficient' } as never,
      suspension_count: { metric_id: 'suspension_count', value: 0, unit: '车次日', quality: 'ok' } as never,
    },
  })
  vi.mocked(api.metrics).mockResolvedValue({
    context: {} as never, granularity: 'day', strict_unavailable: 0,
    items: [
      { metric_id: 'weibo_count', hour_bj: '2023-07-26T00:00:00', value: 1 } as never,
      { metric_id: 'weibo_count', hour_bj: '2023-07-28T00:00:00', value: 1 } as never,
    ],
  })

  await ctx.bootstrap()
  const wrapper = mount(OverviewView, {
    global: { plugins: [pinia, router], stubs: { TrendChart: true, ProvinceMap: true } },
  })
  const topBar = mount(TopBar, { props: { navOpen: false }, global: { plugins: [pinia, router] } })
  await settle()

  expect(api.summary).toHaveBeenLastCalledWith({ dataset_id: 'demo', event_id: 1 }, expect.any(AbortSignal))
  expect(api.metrics).toHaveBeenLastCalledWith(
    { dataset_id: 'demo', event_id: 1, metric_id: 'weibo_count,government_weibo_count,suspension_count' }, expect.any(AbortSignal),
  )
  expect(wrapper.text()).toContain('全国 · 按日统计')
  expect(wrapper.text()).toContain('车次日')
  expect(wrapper.text()).toContain('所选时段缺测')
  expect(wrapper.text()).not.toContain('指标时刻')
  expect(wrapper.find('button[aria-label="开始回放"]').exists()).toBe(false)
  expect(wrapper.getComponent(ProvinceMap).props('typhoon')!.track.length).toBeGreaterThan(2)
  expect(wrapper.getComponent(TrendChart).props('series')[0].data).toEqual([
    ['2023-07-26T00:00:00', 1], ['2023-07-27T00:00:00', null], ['2023-07-28T00:00:00', 1],
  ])
  expect(topBar.text()).not.toContain('当时已知')
  expect(topBar.text()).not.toContain('北京时间')
  topBar.unmount()
  wrapper.unmount()
})

it('limits the historical overlay to Doksuri and leaves only warning lines in as_known mode', async () => {
  vi.mocked(api.metrics).mockResolvedValue({ context: {} as never, granularity: 'hour', strict_unavailable: 0, items: [] })
  vi.mocked(api.summary).mockResolvedValue({
    context: {} as never, data_mode: 'demo', empty: false, cards: {}, freshness: [], card_hour: '2023-07-28T10:00:00',
  })
  const { pinia, router, ctx } = setup('/overview')
  router.addRoute({ path: '/overview/impact', component: { template: '<div />' } })
  ctx.events = [{ ...EVENT, event_code: 'SIM-DOKSURI-2023', external_typhoon_id: 'SIM-202305' }, EVENT_B]
  const wrapper = mount(OverviewView, {
    global: { plugins: [pinia, router], stubs: { TrendChart: true, ProvinceMap: true } },
  })
  const map = () => wrapper.getComponent({ name: 'ProvinceMap' })
  await settle()
  expect(wrapper.text()).toContain('历史路径')
  expect(map().props('typhoon').track.length).toBeGreaterThan(2)
  expect(map().props('typhoon').warnings.map((line: { hours: number }) => line.hours)).toEqual([48, 24])
  expect(map().props('metricTime')).toBe('2023-07-28T10:00:00')

  await wrapper.get('button[aria-label="后退一小时"]').trigger('click')
  await settle()
  expect(ctx.cursor).toBe('2023-07-28T10:00:00')
  expect(api.summary).toHaveBeenLastCalledWith(
    expect.objectContaining({ hour_bj: '2023-07-28T10:00:00' }),
    expect.any(AbortSignal),
  )

  ctx.replayMode = 'as_known'
  await settle()
  expect(map().props('typhoon').track).toHaveLength(0)
  expect(map().props('typhoon').warnings).toHaveLength(2)
  expect(map().props('metricTime')).toBeUndefined()

  ctx.selectEvent(EVENT_B.id)
  await settle()
  expect(map().props('typhoon')).toBeUndefined()
  wrapper.unmount()
})

it('keeps the map in place while the next playback hour is loading', async () => {
  vi.useFakeTimers({ toFake: ['setInterval', 'clearInterval'] })
  const initialHour = '2023-07-28T11:00:00'
  const nextHour = '2023-07-28T12:00:00'
  const response = {
    context: {} as never, data_mode: 'demo' as const, empty: false, cards: {}, freshness: [], card_hour: initialHour,
  }
  let finishRefresh!: (result: typeof response) => void
  const nextResponse = new Promise<typeof response>((resolve) => { finishRefresh = resolve })
  vi.mocked(api.summary).mockResolvedValueOnce(response).mockReturnValueOnce(nextResponse)
  vi.mocked(api.metrics).mockResolvedValue({ context: {} as never, granularity: 'hour', strict_unavailable: 0, items: [] })

  const { pinia, router, ctx } = setup('/overview')
  ctx.replayMode = 'retrospective'
  router.addRoute({ path: '/overview/impact', component: { template: '<div />' } })
  const wrapper = mount(OverviewView, {
    global: { plugins: [pinia, router], stubs: { TrendChart: true, ProvinceMap: true } },
  })

  try {
    await settle()
    const map = wrapper.get('.map-col').element
    await wrapper.get('button[aria-label="开始回放"]').trigger('click')
    await vi.advanceTimersByTimeAsync(719)
    expect(ctx.cursor).toBe(initialHour)
    await vi.advanceTimersByTimeAsync(1)
    expect(api.summary).toHaveBeenLastCalledWith(expect.objectContaining({ hour_bj: nextHour }), expect.any(AbortSignal))
    expect(wrapper.get('.map-col').element).toBe(map)
    expect(wrapper.get('.metric-hour').text()).toContain('2023-07-28 11:00')
    expect(wrapper.text()).not.toContain('正在按新条件刷新')

    finishRefresh({ ...response, card_hour: nextHour })
    await settle()
    expect(wrapper.get('.metric-hour').text()).toContain('2023-07-28 12:00')

    const speeds = wrapper.get('[aria-label="倍速"]').findAll('button')
    await speeds[1].trigger('click')
    await vi.advanceTimersByTimeAsync(360)
    expect(ctx.cursor).toBe('2023-07-28T13:00:00')
    await speeds[2].trigger('click')
    await vi.advanceTimersByTimeAsync(180)
    expect(ctx.cursor).toBe('2023-07-28T14:00:00')
    await wrapper.get('button[aria-label="暂停回放"]').trigger('click')
    await vi.advanceTimersByTimeAsync(720)
    expect(ctx.cursor).toBe('2023-07-28T14:00:00')
  } finally {
    wrapper.unmount()
    vi.useRealTimers()
  }
})
