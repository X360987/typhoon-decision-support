import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api, type Params } from '../src/api/client'
import type { TimelineItem } from '../src/api/types'
import ReplayView from '../src/views/ReplayView.vue'
import { CURSOR, setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
const mocked = vi.mocked(api, true)

const ITEMS: TimelineItem[] = [
  { kind: 'official_post', time: '2023-07-28T08:55:00', known_at: '2023-07-28T09:00:00', label: '早先公告', ref: 'weibo_raw:1', province_code: 'FJ' },
  { kind: 'suspension_notice', time: '2023-07-28T12:00:00', known_at: '2023-07-28T13:00:00', label: '游标后公告', ref: 'train_suspension:2', province_code: null },
]

function mockApis() {
  mocked.metrics.mockResolvedValue({ context: {} as never, granularity: 'hour', strict_unavailable: 0, items: [] })
  mocked.summary.mockResolvedValue({ context: {} as never, data_mode: 'demo', empty: false, cards: {} })
  // The server applies as_of; the mock mimics it so the view can be checked end to end.
  mocked.timeline.mockImplementation(async (p: Params) => ({
    context: {} as never,
    items: ITEMS.filter((i) => !p.as_of || (i.known_at as string) <= String(p.as_of)),
  }))
}

function mountReplay() {
  const env = setup('/replay')
  const wrapper = mount(ReplayView, {
    global: { plugins: [env.pinia, env.router], stubs: { TrendChart: true, ProvinceMap: true, TimeAxis: true } },
  })
  return { ...env, wrapper }
}

describe('ReplayView truncation', () => {
  it('as_known requests stop at the cursor and nothing after the cursor is listed', async () => {
    mockApis()
    const { ctx, wrapper } = mountReplay()
    ctx.replayMode = 'as_known'
    await settle()
    const p = mocked.timeline.mock.calls.at(-1)![0]
    expect(p.as_of).toBe(CURSOR)
    expect(p.known_to).toBe(CURSOR)
    expect(p.known_from).toBe('2023-07-27T23:00:00')
    const metricsParams = mocked.metrics.mock.calls.at(-1)![0]
    expect(metricsParams).toMatchObject({ replay_mode: 'as_known', as_of: CURSOR })
    expect(wrapper.findAll('.log tbody tr')).toHaveLength(1)
    expect(wrapper.findAll('tr.future')).toHaveLength(0)
    expect(wrapper.text()).not.toContain('游标后公告')
  })

  it('retrospective shows later records but tags them as learned after the cursor', async () => {
    mockApis()
    const { ctx, wrapper } = mountReplay()
    ctx.replayMode = 'retrospective'
    await settle()
    const p = mocked.timeline.mock.calls.at(-1)![0]
    expect(p.as_of).toBeUndefined()
    expect(p.known_to).toBe('2023-07-28T17:00:00')
    const future = wrapper.findAll('tr.future')
    expect(future).toHaveLength(1)
    expect(future[0].text()).toContain('游标后获知')
    expect(future[0].text()).toContain('游标后公告')
  })

  it('moving the cursor reloads the log for the new window', async () => {
    mockApis()
    const { ctx } = mountReplay()
    ctx.replayMode = 'as_known'
    await settle()
    const calls = mocked.timeline.mock.calls.length
    ctx.stepCursor(-3)
    await settle()
    expect(mocked.timeline.mock.calls.length).toBeGreaterThan(calls)
    expect(mocked.timeline.mock.calls.at(-1)![0].known_to).toBe('2023-07-28T08:00:00')
  })
})
