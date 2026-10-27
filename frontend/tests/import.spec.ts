import { mount, type VueWrapper } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import { api } from '../src/api/client'
import type { PrecheckReport } from '../src/api/types'
import DataView from '../src/views/DataView.vue'
import { EVENT, setup, settle } from './helpers'

vi.mock('../src/api/client', async (orig) => (await import('./mock-client')).mockClient(orig as never))
const mocked = vi.mocked(api, true)

const HEADER = 'source_id,user_id,content,published_at,available_at,publish_location'
const CSV = `${HEADER}\nA1,U1,福建关注台风,2023-07-27 10:15:00,2023-07-27 10:20:00,福建\nA2,U2,时间写错,not-a-date,,广东\n`

function report(extra: Partial<PrecheckReport> = {}): PrecheckReport {
  return {
    ok: false,
    entity: 'weibo',
    rows: 2,
    columns: HEADER.split(','),
    error_rows: [{ row: 3, reasons: ['published_at 无法解析'], blocking: true, duplicate: false }],
    blocking_errors: 1,
    duplicates: 0,
    warnings: 0,
    time_range: null,
    province_coverage: {},
    checks: [{ name: '时间格式', status: 'fail', detail: '1 处无法解析' }],
    preview: [
      { row: 2, published_at: '2023-07-27T10:15:00', publish_location: '福建', content: '福建关注台风', status: 'ok' },
      { row: 3, published_at: null, publish_location: '广东', content: '时间写错', status: 'error' },
    ],
    precheck_token: 'tok-1',
    allowed_policies: ['skip_errors'],
    file_name: 'bad.csv',
    ...extra,
  }
}

function mockApis() {
  mocked.importSources.mockResolvedValue({
    max_upload_mb: 20,
    items: [
      { entity: 'weibo', name: '微博', status: 'supported' },
      { entity: 'timetable', name: '列车时刻表', status: 'not_connected' },
    ],
  })
  mocked.batches.mockResolvedValue({ items: [] })
  mocked.coverage.mockResolvedValue({
    context: {} as never,
    event_hours: 72,
    run: null,
    tasks: {},
    pending_mapping: [],
    account_classes: {},
    untrusted_arrival: null,
    org_covered_provinces: [],
    metric_matrix: {},
    low_sample_hours: {},
    unknown_arrival_metric_rows: 0,
    proxy_sources: [],
  })
  mocked.runs.mockResolvedValue({ items: [] })
  mocked.events.mockResolvedValue({ items: [EVENT, { ...EVENT, id: 2 }] })
  mocked.precheck.mockResolvedValue(report())
  mocked.commit.mockResolvedValue({ ok: true, import_status: 'imported', analysis_status: 'success', batch_id: 9, inserted: 1, skipped: 0 })
}

const commitButton = (w: VueWrapper) => w.findAll('.import-step button').find((b) => b.text().includes('确认导入'))!
const clickText = async (w: VueWrapper, text: string) => {
  await w.findAll('.import-step button').find((b) => b.text().includes(text))!.trigger('click')
  await settle()
}

async function toPrecheck() {
  const env = setup('/data')
  await env.router.isReady()
  const wrapper = mount(DataView, { global: { plugins: [env.pinia, env.router] } })
  await settle()
  const input = wrapper.find('input[type="file"]')
  Object.defineProperty(input.element, 'files', { value: [new File([CSV], 'bad.csv', { type: 'text/csv' })] })
  await input.trigger('change')
  await settle()
  await clickText(wrapper, '下一步')
  return { ...env, wrapper }
}

describe('DataView import', () => {
  it('lists sources without an import path as not connected', async () => {
    mockApis()
    const env = setup('/data')
    const wrapper = mount(DataView, { global: { plugins: [env.pinia, env.router] } })
    await settle()
    const option = wrapper.findAll('option').find((o) => o.text().includes('列车时刻表'))!
    expect(option.text()).toContain('未接入')
    expect(option.attributes('disabled')).toBeDefined()
  })

  it('parses the header for mapping, blocks commit on blocking errors and explains why', async () => {
    mockApis()
    const { wrapper } = await toPrecheck()
    const mappingRows = wrapper.findAll('.import-step tbody tr')
    expect(mappingRows.map((r) => r.find('td').text())).toEqual(HEADER.split(','))
    await clickText(wrapper, '运行预检')

    const form = mocked.precheck.mock.calls[0][0] as FormData
    expect(form.get('entity')).toBe('weibo')
    expect(form.get('dataset_id')).toBe('demo')
    expect(form.get('event_id')).toBe('1')
    expect((form.get('file') as File).name).toBe('bad.csv')

    expect(commitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('.import-step .note.attn').text()).toContain('阻断错误')
    expect(wrapper.find('.quality').text()).toContain('时间格式')
  })

  it('skip_errors needs explicit confirmation and sends the excluded-row policy', async () => {
    mockApis()
    const { ctx, wrapper } = await toPrecheck()
    await clickText(wrapper, '运行预检')
    await wrapper.find('input[type="radio"][value="skip_errors"]').setValue(true)
    expect(commitButton(wrapper).attributes('disabled')).toBeDefined()
    expect(wrapper.find('.skip-list').text()).toContain('第 3 行')
    await wrapper.find('.skip-list input[type="checkbox"]').setValue(true)
    expect(commitButton(wrapper).attributes('disabled')).toBeUndefined()
    const revision = ctx.revision
    await commitButton(wrapper).trigger('click')
    await settle()
    const form = mocked.commit.mock.calls[0][0] as FormData
    expect(form.get('precheck_token')).toBe('tok-1')
    expect(form.get('error_policy')).toBe('skip_errors')
    expect(form.get('confirm_skip')).toBe('true')
    const result = wrapper.find('.result').text()
    expect(result).toContain('导入状态')
    expect(result).toContain('分析状态')
    expect(ctx.revision).toBe(revision + 1)
    expect(mocked.events).toHaveBeenCalledWith('demo')
  })

  it('a clean file can be committed under the strict policy', async () => {
    mockApis()
    mocked.precheck.mockResolvedValue(report({ ok: true, error_rows: [], blocking_errors: 0, allowed_policies: ['strict'] }))
    const { wrapper } = await toPrecheck()
    await clickText(wrapper, '运行预检')
    expect(commitButton(wrapper).attributes('disabled')).toBeUndefined()
    await commitButton(wrapper).trigger('click')
    await settle()
    expect((mocked.commit.mock.calls[0][0] as FormData).get('error_policy')).toBe('strict')
  })
})
