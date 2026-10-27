import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { defineComponent, h, ref } from 'vue'
import { api } from '../src/api/client'
import ContextGate from '../src/components/ContextGate.vue'
import { useLoader, type Loader } from '../src/composables/useLoader'
import { fmtTime, toBeijing } from '../src/lib/format'
import { setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
const mocked = vi.mocked(api, true)

function harness<T>(make: () => Loader<T>) {
  let loader!: Loader<T>
  const wrapper = mount(
    defineComponent({
      setup() {
        loader = make()
        return () => h('div')
      },
    }),
  )
  return { loader, wrapper }
}

describe('useLoader under fast context switching', () => {
  it('never lets a slow response for old parameters overwrite newer data', async () => {
    const key = ref('event-1')
    const pending: Array<{ key: string; signal: AbortSignal; resolve: (v: string) => void }> = []
    const { loader } = harness(() =>
      useLoader(
        (signal) => new Promise<string>((resolve) => pending.push({ key: key.value, signal, resolve })),
        () => key.value,
      ),
    )
    await settle()
    key.value = 'event-2'
    await settle()
    expect(pending.map((p) => p.key)).toEqual(['event-1', 'event-2'])
    expect(pending[0].signal.aborted).toBe(true)
    pending[1].resolve('data-2')
    await settle()
    pending[0].resolve('data-1')
    await settle()
    expect(loader.data.value).toBe('data-2')
    expect(loader.status.value).toBe('ready')
  })

  it('clears data when the dataset/event scope changes instead of showing it as stale', async () => {
    const scope = ref('demo|1')
    const pending: Array<(v: string) => void> = []
    const { loader } = harness(() =>
      useLoader(
        () => new Promise<string>((resolve) => pending.push(resolve)),
        () => scope.value,
        { scope: () => scope.value },
      ),
    )
    await settle()
    pending[0]('event-1 rows')
    await settle()
    expect(loader.data.value).toBe('event-1 rows')
    scope.value = 'demo|2'
    await settle()
    expect(loader.data.value).toBeNull()
    expect(loader.stale.value).toBe(false)
    expect(loader.status.value).toBe('loading')
  })
})

describe('context store and gate', () => {
  it('real mode with no dataset stays empty and never seeds demo data', async () => {
    const { ctx, pinia, router } = setup()
    mocked.health.mockResolvedValue({ status: 'ok', database: true, error: null, data_mode: 'real', write_requires_key: true, seed_allowed: false, time: '' })
    mocked.datasets.mockResolvedValue({ data_mode: 'real', items: [] })
    await ctx.bootstrap()
    expect(ctx.bootError).toBe('')
    expect(ctx.bootStatus).toBe('no_dataset')
    expect(ctx.events).toEqual([])
    expect(mocked.seed).not.toHaveBeenCalled()
    const wrapper = mount(ContextGate, { slots: { default: '<p class="content">content</p>' }, global: { plugins: [pinia, router] } })
    expect(wrapper.find('.content').exists()).toBe(false)
    expect(wrapper.text()).toContain('不会用演示数据填充')
  })

  it('switching events resets cursor and version so pages do not mix events', () => {
    const { ctx } = setup()
    ctx.dataVersion = 'r9'
    const before = ctx.scopeKey
    ctx.selectEvent(2)
    expect(ctx.scopeKey).not.toBe(before)
    expect(ctx.dataVersion).toBe('')
    expect(ctx.cursor?.startsWith('2023-09-06')).toBe(true)
    expect(ctx.params).toMatchObject({ dataset_id: 'demo', event_id: 2 })
  })

  it('as_known mode sends as_of = cursor in shared params; retrospective omits it', () => {
    const { ctx } = setup()
    ctx.replayMode = 'as_known'
    expect(ctx.params.as_of).toBe('2023-07-28T11:00:00')
    ctx.replayMode = 'retrospective'
    expect(ctx.params.as_of).toBeUndefined()
  })
})

describe('time formatting', () => {
  it('keeps naive Beijing times and converts UTC system timestamps to Beijing', () => {
    expect(fmtTime('2023-07-28T11:00:00')).toBe('2023-07-28 11:00')
    expect(toBeijing('2026-10-26T03:55:00Z')).toBe('2026-10-26T11:55:00')
    expect(fmtTime('2026-10-26T20:30:00Z')).toBe('2026-10-27 04:30')
  })
})
