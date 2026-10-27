export type DataMode = 'demo' | 'real'
export type ReplayMode = 'as_known' | 'retrospective'
export type Scope = 'single' | 'pair' | 'joint'
export type Dimension = 'social' | 'organizational' | 'physical'
export type ReviewAction = 'approve' | 'reject' | 'need_evidence'

export interface ApiErrorDetail {
  error_code?: string
  message?: string
  [key: string]: unknown
}

export interface ContextInfo {
  dataset_id: string
  data_mode: DataMode
  event_id: number
  data_version: string
  active_version: string
  province_code: string | null
  start: string | null
  end: string | null
  as_of: string | null
  replay_mode: ReplayMode
  analysis_scope: Scope | null
  dimension: Dimension | null
  timezone: string
}

export interface Health {
  status: string
  database: boolean
  error: string | null
  data_mode: DataMode
  write_requires_key: boolean
  seed_allowed: boolean
  time: string
}

export interface Dataset {
  id: string
  name: string
  data_mode: DataMode
  description: string | null
}

export interface EventItem {
  id: number
  dataset_id: string
  event_code: string
  name: string
  external_typhoon_id: string | null
  start_time: string
  end_time: string
  status: string
  config_version: string
  active_version: string
}

export interface MetricPoint {
  province_code: string
  hour_bj: string
  metric_id: string
  value: number | null
  sample_size: number | null
  coverage: number | null
  quality_status: string
  unit: string | null
  version: string
  available_at: string | null
}

export interface MetricSeriesResponse {
  context: ContextInfo
  granularity: string
  strict_unavailable: number
  items: MetricPoint[]
}

export interface RegistryMetric {
  id: string
  name: string
  dimension: string
  unit: string | null
  description: string | null
  aggregation: string | null
  numerator: string | null
  denominator: string | null
  dedup_key: string | null
  national_rule: string | null
  version: string
}

export interface RegistryResponse {
  rule_version: string
  rules: Record<string, Record<string, unknown> | null>
  items: RegistryMetric[]
}

export interface Anomaly {
  id: number
  analysis_scope: Scope
  dimensions: Dimension[]
  anomaly_type: string
  province_code: string
  hour_bj: string
  available_at: string | null
  requires_future_window: boolean
  nature: string
  score: number | null
  baseline: number | null
  threshold: number | null
  quality_status: string
  rule_version: string
  data_version: string
  group_key: string
  explanation: string | null
  review_status: string
}

export interface AnomalyListResponse {
  context: ContextInfo
  total: number
  page: number
  page_size: number
  counts: { single: number; pair: number; joint: number; unique_groups: number }
  pending_window: number
  items: Anomaly[]
}

export interface EvidenceSource {
  kind: 'weibo' | 'suspension'
  content: string | null
  url: string | null
  simulated: boolean
  source_id?: string
  user?: string
  account_class?: string | null
  published_at?: string | null
  available_at?: string | null
  ingested_at?: string | null
  publish_location?: string | null
  region_basis?: Array<{ province_code: string; method: string }>
  record_no?: string
  train_code?: string
  scope?: string | null
  segment?: Array<string | null>
  notice_account?: string | null
  known_at?: string | null
  suspension_date?: string | null
  scope_basis?: string | null
}

export interface Evidence {
  id: number
  evidence_type: string
  summary: string | null
  payload: Record<string, unknown> | null
  ref_table: string | null
  ref_id: string | null
  source: EvidenceSource | null
}

export interface ReviewRecord {
  id: number
  action: ReviewAction
  note: string | null
  operator: string | null
  created_at: string | null
}

export interface Suggestion {
  id: number
  anomaly_id?: number | null
  suggestion_code: string
  text: string
  trigger_reason: string | null
  review_status: string
}

export interface AnomalyDetail {
  visible_at_as_of: boolean
  anomaly: Anomaly & {
    dataset_id: string
    event_id: number
    decided_at: string | null
    hazard_context: unknown
    sample: { metric_id: string; value: number | null; sample_size: number | null; coverage: number | null } | null
    evidence_status: 'sufficient' | 'insufficient'
  }
  evidences: Evidence[]
  suggestions: Suggestion[]
  reviews: ReviewRecord[]
}

export interface SummaryCard {
  metric_id: string
  name: string
  unit: string | null
  hour_bj: string
  provinces: Record<string, number | null>
  value: number | null
  sample_size: number | null
  aggregation: string | null
  quality: 'ok' | 'insufficient' | 'strict_unavailable'
}

export interface SummaryResponse {
  context: ContextInfo
  data_mode: DataMode
  empty: boolean
  message?: string
  phase?: 'pre' | 'during' | 'post'
  card_hour?: string
  event?: { id: number; name: string; event_code: string; start_time: string; end_time: string; status: string }
  banner?: string
  cards: Record<string, SummaryCard>
  anomaly_counts?: { single: number; pair: number; joint: number }
  pending_window?: number
  to_review?: Anomaly[]
  freshness?: Array<{ source: string; latest: string | null }>
}

export interface ForecastResponse {
  context: ContextInfo
  items: Array<{ id: number; source: string; issued_at: string; arrived_at: string; revision: number | null }>
  latest_points: Array<{
    valid_time: string
    lead_hours: number
    lat: number | null
    lon: number | null
    metric: string
    value: number | null
    unit: string | null
    province_code: string | null
  }>
}

export interface PredictionItem {
  target_id: string
  unit: string | null
  province_code: string
  origin_time: string
  valid_time: string
  lead_hours: number
  point_pred: number | null
  interval_low: number | null
  interval_high: number | null
  interval_reason: string | null
  status: string
  reason: string | null
  model_version: string
  train_cutoff: string | null
  data_version: string
  quality_status: string
}

export interface PredictionsResponse {
  context: ContextInfo
  run: { id: number; origin_time: string; model_version: string; status: string; created_at: string | null } | null
  available_origins: string[]
  targets: Array<{ id: string; name: string; unit: string | null }>
  horizons: number[]
  ml_horizon: number
  cross_event_validated: boolean
  interval_reason: string
  items: PredictionItem[]
}

export interface TaskResult {
  task_id: number
  status: string
  result?: Record<string, unknown> | null
  operator?: string
  [key: string]: unknown
}

export interface ModelItem {
  model_key: string
  target_id: string
  horizon_hours: number
  model_kind: string
  data_mode: DataMode
  metrics: Record<string, number | string | null> | null
  feature_contract: { version: string; names: string[]; missing: string } | null
  train_window: Record<string, string | number> | null
  version: string
}

export interface AnalysisRunItem {
  id: number
  event_id: number
  data_version: string | null
  status: string
  rule_version: string
  trigger: string
  message: string | null
  started_at: string | null
  finished_at: string | null
  active: boolean
}

export interface CoverageResponse {
  context: ContextInfo
  event_hours: number
  run: { id: number; status: string; finished_at: string | null } | null
  tasks: Record<string, Record<string, string>>
  pending_mapping: Array<{ suspension_id: number; record_no: string; train_code: string; reason: string }>
  account_classes: Record<string, number>
  untrusted_arrival: number | null
  org_covered_provinces: string[]
  metric_matrix: Record<string, Record<string, { hours: number; samples: number }>>
  low_sample_hours: Record<string, number>
  unknown_arrival_metric_rows: number
  proxy_sources: Array<{ metric: string; note: string }>
}

export interface TopicsResponse {
  context: ContextInfo
  method: string
  sample_size: number
  items: Array<{ keyword: string; count: number }>
}

export interface TimelineItem {
  kind: 'official_post' | 'suspension_notice' | 'anomaly'
  time: string | null
  known_at: string | null
  label: string
  ref: string
  province_code: string | null
}

export interface ImpactSuspension {
  id: number
  record_no: string
  train_code: string
  suspension_date: string | null
  known_at: string | null
  scope: string | null
  segment: Array<string | null>
  provinces: string[]
  stations: string[]
  mapping_status: 'mapped' | 'pending_review' | 'unmapped'
  pending_reason: string | null
  basis: string[]
  notice_account: string | null
}

export interface ImpactResponse {
  context: ContextInfo
  suspensions: ImpactSuspension[]
  run_instances: Array<{ run_key: string; train_code: string; provinces: string[]; first_hour: string; last_hour: string }>
  recovery: { status: string; message: string }
}

export interface ActionTask {
  id: number
  suggestion_id: number
  title: string
  owner: string | null
  due_at: string | null
  status: 'open' | 'in_progress' | 'done' | 'closed' | 'cancelled'
  receipt: string | null
  review_note: string | null
  created_by: string | null
  created_at: string | null
  updated_at: string | null
}

export interface ImportSource {
  entity: string
  name: string
  status: 'supported' | 'not_connected'
  template?: string
}

export interface PrecheckRow {
  row: number
  published_at: string | null
  publish_location: string | null
  content: string
  status: 'ok' | 'error' | 'duplicate' | 'warning'
}

export interface PrecheckReport {
  ok: boolean
  entity: string
  rows: number
  columns: string[]
  error?: string
  message?: string
  error_rows: Array<{ row: number; reasons: string[]; blocking: boolean; duplicate: boolean }>
  blocking_errors: number
  duplicates: number
  warnings: number
  time_range: { start: string; end: string } | null
  province_coverage: Record<string, number>
  checks: Array<{ name: string; status: 'pass' | 'warn' | 'fail'; detail: string }>
  preview: PrecheckRow[]
  precheck_token: string | null
  allowed_policies: Array<'strict' | 'skip_errors'>
  file_name?: string
}

export interface CommitResult {
  ok: boolean
  import_status: 'imported' | 'idempotent_reuse'
  analysis_status: string | null
  batch_id: number
  inserted?: number
  skipped?: number
  excluded_rows?: Array<{ row: number; reasons: string[] }>
}

export interface BatchItem {
  id: number
  event_id: number | null
  source_type: string
  status: string
  file_name: string | null
  created_at: string | null
  completed_at: string | null
  inserted: number | null
  excluded_rows: number
  analysis_status: string | null
}
