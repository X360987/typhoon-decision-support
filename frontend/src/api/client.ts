import type {
  ActionTask,
  AnalysisRunItem,
  AnomalyDetail,
  AnomalyListResponse,
  ApiErrorDetail,
  BatchItem,
  CommitResult,
  CoverageResponse,
  Dataset,
  EventItem,
  ForecastResponse,
  Health,
  ImpactResponse,
  ImportSource,
  MetricSeriesResponse,
  ModelItem,
  PrecheckReport,
  PredictionsResponse,
  RegistryResponse,
  ReviewAction,
  ReviewRecord,
  Suggestion,
  SummaryResponse,
  TaskResult,
  TimelineItem,
  TopicsResponse,
  ContextInfo,
} from './types'

const API_BASE: string = import.meta.env.VITE_API_BASE ?? 'http://localhost:8000'

const KEY_STORE = 'typhoon.apiKey'
const OPERATOR_STORE = 'typhoon.operator'

/** Credentials live in sessionStorage only for the current tab; nothing secret is compiled into the bundle. */
export const credentials = {
  get apiKey(): string {
    return sessionStorage.getItem(KEY_STORE) || ''
  },
  get operator(): string {
    return sessionStorage.getItem(OPERATOR_STORE) || ''
  },
  save(apiKey: string, operator: string) {
    if (apiKey) sessionStorage.setItem(KEY_STORE, apiKey)
    else sessionStorage.removeItem(KEY_STORE)
    if (operator) sessionStorage.setItem(OPERATOR_STORE, operator)
    else sessionStorage.removeItem(OPERATOR_STORE)
  },
}

export class ApiError extends Error {
  status: number
  detail: ApiErrorDetail

  constructor(status: number, detail: ApiErrorDetail) {
    super(detail.message || `HTTP ${status}`)
    this.status = status
    this.detail = detail
  }
}

export type Params = Record<string, string | number | boolean | null | undefined>

export function query(params: Params): string {
  const q = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v === null || v === undefined || v === '') continue
    q.set(k, String(v))
  }
  const s = q.toString()
  return s ? `?${s}` : ''
}

interface RequestOptions {
  method?: string
  body?: unknown
  form?: FormData
  signal?: AbortSignal
  write?: boolean
}

async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' }
  if (opts.write) {
    if (credentials.apiKey) headers['X-API-Key'] = credentials.apiKey
    if (credentials.operator) headers['X-Operator'] = credentials.operator
  }
  let body: BodyInit | undefined
  if (opts.form) body = opts.form
  else if (opts.body !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.body)
  }
  const res = await fetch(`${API_BASE}${path}`, { method: opts.method || 'GET', headers, body, signal: opts.signal })
  if (!res.ok) {
    let detail: ApiErrorDetail = { message: res.statusText }
    try {
      const data = await res.json()
      const d = data.detail ?? data
      detail = Array.isArray(d) ? { error_code: 'validation_error', message: d.map((x) => x.msg).join('; ') } : d
    } catch {
      /* body was not JSON */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export function isAbort(e: unknown): boolean {
  return e instanceof DOMException && e.name === 'AbortError'
}

const V1 = '/api/v1'

export const api = {
  base: API_BASE,
  health: (signal?: AbortSignal) => request<Health>(`${V1}/health`, { signal }),
  datasets: () => request<{ data_mode: string; items: Dataset[] }>(`${V1}/datasets`),
  events: (datasetId: string) => request<{ items: EventItem[] }>(`${V1}/events${query({ dataset_id: datasetId })}`),
  createEvent: (body: { dataset_id: string; event_code: string; name: string; start_time: string; end_time: string }) =>
    request<{ id: number }>(`${V1}/events`, { method: 'POST', body, write: true }),
  seed: () => request<Record<string, unknown>>(`${V1}/admin/seed`, { method: 'POST', write: true }),

  registry: (signal?: AbortSignal) => request<RegistryResponse>(`${V1}/metrics/registry`, { signal }),
  metrics: (p: Params, signal?: AbortSignal) => request<MetricSeriesResponse>(`${V1}/metrics/series${query(p)}`, { signal }),
  summary: (p: Params, signal?: AbortSignal) => request<SummaryResponse>(`${V1}/dashboard/summary${query(p)}`, { signal }),
  forecasts: (p: Params, signal?: AbortSignal) => request<ForecastResponse>(`${V1}/forecasts${query(p)}`, { signal }),
  topics: (p: Params, signal?: AbortSignal) => request<TopicsResponse>(`${V1}/analysis/topics${query(p)}`, { signal }),
  timeline: (p: Params, signal?: AbortSignal) =>
    request<{ context: ContextInfo; items: TimelineItem[] }>(`${V1}/timeline${query(p)}`, { signal }),
  impact: (p: Params, signal?: AbortSignal) => request<ImpactResponse>(`${V1}/impact${query(p)}`, { signal }),
  coverage: (p: Params, signal?: AbortSignal) => request<CoverageResponse>(`${V1}/coverage${query(p)}`, { signal }),
  runs: (p: Params, signal?: AbortSignal) => request<{ items: AnalysisRunItem[] }>(`${V1}/analysis/runs${query(p)}`, { signal }),

  anomalies: (p: Params, signal?: AbortSignal) => request<AnomalyListResponse>(`${V1}/anomalies${query(p)}`, { signal }),
  anomalyDetail: (id: number, p: Params, signal?: AbortSignal) =>
    request<AnomalyDetail>(`${V1}/anomalies/${id}${query(p)}`, { signal }),
  suggestions: (p: Params, signal?: AbortSignal) =>
    request<{ context: ContextInfo; items: Suggestion[] }>(`${V1}/suggestions${query(p)}`, { signal }),
  review: (body: { dataset_id: string; target_type: 'anomaly' | 'suggestion'; target_id: number; action: ReviewAction; note?: string }) =>
    request<{ ok: boolean; id: number; operator: string; created_at: string }>(`${V1}/review`, { method: 'POST', body, write: true }),
  reviews: (p: Params, signal?: AbortSignal) => request<{ items: ReviewRecord[] }>(`${V1}/reviews${query(p)}`, { signal }),

  predictions: (p: Params, signal?: AbortSignal) => request<PredictionsResponse>(`${V1}/predictions${query(p)}`, { signal }),
  runPrediction: (body: { dataset_id: string; event_id: number; origin_time: string }) =>
    request<TaskResult>(`${V1}/predictions/run`, { method: 'POST', body, write: true }),
  models: (signal?: AbortSignal) => request<{ items: ModelItem[] }>(`${V1}/models`, { signal }),

  rerun: (datasetId: string, eventId: number) =>
    request<TaskResult>(`${V1}/pipeline/rerun${query({ dataset_id: datasetId, event_id: eventId })}`, { method: 'POST', write: true }),

  importSources: () => request<{ items: ImportSource[]; max_upload_mb: number }>(`${V1}/import/sources`),
  precheck: (form: FormData) => request<PrecheckReport>(`${V1}/import/precheck`, { method: 'POST', form, write: true }),
  commit: (form: FormData) => request<CommitResult>(`${V1}/import/commit`, { method: 'POST', form, write: true }),
  batches: (datasetId: string, signal?: AbortSignal) =>
    request<{ items: BatchItem[] }>(`${V1}/import/batches${query({ dataset_id: datasetId })}`, { signal }),
  importErrors: (batchId: number, datasetId: string) =>
    request<{ batch_id: number; status: string; items: Array<{ row_number: number; reason: string; raw_payload: Record<string, unknown> }> }>(
      `${V1}/import/errors/${batchId}${query({ dataset_id: datasetId })}`,
    ),

  actions: (p: Params, signal?: AbortSignal) => request<{ items: ActionTask[] }>(`${V1}/actions${query(p)}`, { signal }),
  createAction: (body: { dataset_id: string; suggestion_id: number; title?: string; owner?: string; due_at?: string }) =>
    request<ActionTask>(`${V1}/actions`, { method: 'POST', body, write: true }),
  updateAction: (id: number, body: { dataset_id: string; status?: string; receipt?: string; owner?: string; review_note?: string }) =>
    request<ActionTask>(`${V1}/actions/${id}`, { method: 'PATCH', body, write: true }),

  exportUrl: (kind: 'anomalies' | 'metrics', p: Params) => `${API_BASE}${V1}/export/${kind}${query(p)}`,
}
