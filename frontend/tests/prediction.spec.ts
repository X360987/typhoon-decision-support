import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api, type Params } from '../src/api/client'
import type { MetricPoint, PredictionItem } from '../src/api/types'
import TrendChart, { type ChartSeries } from '../src/components/TrendChart.vue'
import { addHours } from '../src/lib/format'
import PredictionView from '../src/views/PredictionView.vue'
import { setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
const mocked = vi.mocked(api, true)

const ORIGIN = '2023-07-28T11:00:00'
const HORIZONS = [1, 3, 6, 12, 24]

function point(hour: string, value: number): MetricPoint {
  return { province_code: 'ALL', hour_bj: hour, metric_id: 'affected_trains', value, sample_size: 1, coverage: null, quality_status: 'ok', unit: '列/小时', version: 'r1', available_at: hour }
}

function item(h: number): PredictionItem {
  return {
    target_id: 'affected_trains',
    unit: '列/小时',
    province_code: 'ALL',
    origin_time: ORIGIN,
    valid_time: addHours(ORIGIN, h),
    lead_hours: h,
    point_pred: h === 3 ? 1.64 : 1.2,
    interval_low: null,
    interval_high: null,
    interval_reason: 'INTERVAL_UNAVAILABLE',
    status: h === 3 ? 'demo_ml' : 'baseline_naive',
    reason: h === 3 ? null : '仅 h3 有树模型',
    model_version: 'm1',
    train_cutoff: '2023-07-28T04:00:00',
    data_version: 'r1',
    quality_status: 'ok',
  }
}

function mockApis() {
  mocked.predictions.mockResolvedValue({
    context: {} as never,
    run: { id: 1, origin_time: ORIGIN, model_version: 'm1', status: 'success', created_at: null },
    available_origins: [ORIGIN],
    targets: [{ id: 'affected_trains', name: '受影响车次', unit: '列/小时' }],
    horizons: HORIZONS,
    ml_horizon: 3,
    cross_event_validated: false,
    interval_reason: '区间不可用：当前模型与基线均不输出经过校准的预测区间',
    items: HORIZONS.map(item),
  })
  mocked.metrics.mockImplementation(async (p: Params) => {
    const hours = Array.from({ length: 48 }, (_, i) => addHours('2023-07-27T00:00:00', i))
    // as_known history must already be cut at the origin by the server; the extra point checks the client cut too.
    const items = p.replay_mode === 'as_known' ? hours.filter((t) => t <= ORIGIN).map((t) => point(t, 2)) : hours.map((t) => point(t, 3))
    return { context: {} as never, granularity: 'hour', strict_unavailable: 0, items }
  })
}

describe('PredictionView', () => {
  it('draws history before the origin and forecasts after it on one future-extended axis', async () => {
    mockApis()
    const env = setup('/prediction')
    const wrapper = mount(PredictionView, { global: { plugins: [env.pinia, env.router], stubs: { TrendChart: true } } })
    await settle()
    const chart = wrapper.findComponent(TrendChart)
    expect(chart.exists()).toBe(true)
    const props = chart.props() as { series: ChartSeries[]; xMin: string; xMax: string; markers: Array<{ time: string }> }
    expect(props.xMin).toBe(addHours(ORIGIN, -36))
    expect(props.xMax).toBe(addHours(ORIGIN, 24))
    expect(props.markers[0].time).toBe(ORIGIN)
    const [history, future, ml] = props.series
    expect(history.data.length).toBeGreaterThan(0)
    expect(history.data.every(([t]) => t < ORIGIN)).toBe(true)
    expect(future.dashed).toBe(true)
    expect(future.data.slice(1).every(([t]) => t > ORIGIN)).toBe(true)
    expect(future.data.at(-1)![0]).toBe(props.xMax)
    expect(ml.data).toEqual([[addHours(ORIGIN, 3), 1.64]])

    const asKnown = mocked.metrics.mock.calls.find(([p]) => p.replay_mode === 'as_known')![0]
    expect(asKnown.as_of).toBe(ORIGIN)
  })

  it('states that intervals are unavailable instead of drawing invented ones', async () => {
    mockApis()
    const env = setup('/prediction')
    const wrapper = mount(PredictionView, { global: { plugins: [env.pinia, env.router], stubs: { TrendChart: true } } })
    await settle()
    expect(wrapper.text()).toContain('区间不可用')
    expect(wrapper.text()).toContain('未经跨事件验证')
    const rows = wrapper.findAll('.table-wrap tbody tr')
    expect(rows).toHaveLength(5)
    expect(rows[1].text()).toContain('树模型')
    expect(rows[0].text()).toContain('朴素基线')
  })
})
