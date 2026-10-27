import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import type { Anomaly, AnomalyDetail } from '../src/api/types'
import EvidenceView from '../src/views/EvidenceView.vue'
import { setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
const mocked = vi.mocked(api, true)

function anomaly(id: number, extra: Partial<Anomaly> = {}): Anomaly {
  return {
    id,
    analysis_scope: 'single',
    dimensions: ['social'],
    anomaly_type: 'negative_ratio_spike',
    province_code: 'FJ',
    hour_bj: '2023-07-28T10:00:00',
    available_at: '2023-07-28T11:00:00',
    requires_future_window: false,
    nature: 'observed',
    score: 3.4,
    baseline: 0.2,
    threshold: 0.35,
    quality_status: 'ok',
    rule_version: 'rules-v2',
    data_version: 'r1',
    group_key: `g${id}`,
    explanation: `解释 ${id}`,
    review_status: 'pending',
    ...extra,
  }
}

function detail(id: number, eventId = 1): AnomalyDetail {
  return {
    visible_at_as_of: true,
    anomaly: { ...anomaly(id, id === 2 ? { province_code: 'GD' } : {}), dataset_id: 'demo', event_id: eventId, decided_at: null, hazard_context: null, sample: null, evidence_status: 'sufficient' },
    evidences: [],
    suggestions: [],
    reviews: [],
  }
}

function mockApis() {
  mocked.anomalies.mockResolvedValue({
    context: {} as never,
    total: 2,
    page: 1,
    page_size: 20,
    counts: { single: 2, pair: 0, joint: 0, unique_groups: 2 },
    pending_window: 0,
    items: [anomaly(1), anomaly(2, { province_code: 'GD' })],
  })
  mocked.anomalyDetail.mockImplementation(async (id: number) => detail(id))
  mocked.review.mockResolvedValue({ ok: true, id: 10, operator: '值班员', created_at: '2026-10-26T03:55:00Z' })
}

async function mountEvidence(path = '/evidence') {
  const env = setup(path)
  await env.router.isReady()
  const wrapper = mount(EvidenceView, { global: { plugins: [env.pinia, env.router] } })
  await settle()
  return { ...env, wrapper }
}

describe('EvidenceView', () => {
  it('selects an anomaly, records a review with a note and shows the Beijing time of the record', async () => {
    mockApis()
    const { router, wrapper } = await mountEvidence()
    await wrapper.find('[data-anomaly="2"]').trigger('click')
    await settle()
    expect(router.currentRoute.value.params.id).toBe('2')
    expect(wrapper.find('.detail-col h1').text()).toContain('广东')

    await wrapper.find('.review-bar textarea').setValue('需补充原文')
    const button = wrapper.findAll('.review-bar button').find((b) => b.text().includes('待补证据'))!
    await button.trigger('click')
    await settle()
    expect(mocked.review).toHaveBeenCalledWith({
      dataset_id: 'demo',
      target_type: 'anomaly',
      target_id: 2,
      action: 'need_evidence',
      note: '需补充原文',
    })
    const status = wrapper.find('.detail-col [role="status"]').text()
    expect(status).toContain('已记录')
    expect(status).toContain('2026-10-26 11:55')
    expect(mocked.anomalyDetail.mock.calls.filter(([id]) => id === 2).length).toBeGreaterThan(1)
  })

  it('arrow keys move the selection through the list', async () => {
    mockApis()
    const { router, wrapper } = await mountEvidence('/evidence/1')
    await wrapper.find('[data-anomaly="1"]').trigger('keydown', { key: 'ArrowDown' })
    await settle()
    expect(router.currentRoute.value.params.id).toBe('2')
  })

  it('drops detail that belongs to another event and clears the selection when the event changes', async () => {
    mockApis()
    mocked.anomalyDetail.mockImplementation(async (id: number) => detail(id, 2))
    const { ctx, router, wrapper } = await mountEvidence('/evidence/1')
    expect(wrapper.find('.detail-col h1').exists()).toBe(false)
    expect(wrapper.text()).toContain('不属于当前数据集或事件')

    mocked.anomalyDetail.mockImplementation(async (id: number) => detail(id))
    ctx.selectEvent(2)
    await settle()
    expect(router.currentRoute.value.params.id ?? '').toBe('')
  })
})
