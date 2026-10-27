export const PROVINCE_NAMES: Record<string, string> = {
  ALL: '全国（去重）',
  FJ: '福建',
  GD: '广东',
  ZJ: '浙江',
  JS: '江苏',
  SH: '上海',
  TW: '台湾',
  HI: '海南',
  GX: '广西',
}

export function provinceName(code: string | null | undefined): string {
  if (!code) return '全部省份'
  return PROVINCE_NAMES[code] || code
}

export const DIMENSION_NAMES: Record<string, string> = {
  social: '社会',
  organizational: '组织',
  physical: '物理',
  quality: '质量',
}

export function dimensionNames(dims: readonly string[] | null | undefined, sep = ' / '): string {
  return (dims || []).map((d) => DIMENSION_NAMES[d] || d).join(sep)
}

export const SCOPE_NAMES: Record<string, string> = {
  single: '单维',
  pair: '两维关系',
  joint: '三维联合',
}

export const ANOMALY_NAMES: Record<string, string> = {
  negative_ratio_spike: '负面情绪比例升高',
  discussion_spike: '讨论量突增',
  official_publish_spike: '官方发布突增',
  official_publish_gap: '官方发布连续偏低',
  suspension_concentration: '停运集中',
  social_org_mismatch: '社会关注高而官方发布少',
  emotion_without_suspension: '情绪升高但无停运影响',
  emotion_suspension_co_move: '情绪与停运同步升高',
  org_physical_response_lag: '停运后官方公告偏少（滞后）',
  triple_co_movement: '三维同步升高',
  triple_imbalance: '三维关系失衡',
}

export function anomalyName(type: string): string {
  return ANOMALY_NAMES[type] || type
}

export const REVIEW_NAMES: Record<string, string> = {
  pending: '待核验',
  approve: '核验通过',
  reject: '驳回',
  need_evidence: '待补证据',
}

export const PHASE_NAMES: Record<string, { label: string; hint: string }> = {
  pre: { label: '灾前', hint: '风险与准备：关注预警发布、公众关注与准备动作。' },
  during: { label: '灾中', hint: '影响与核查：关注影响范围、待核查异常与官方响应。' },
  post: { label: '灾后', hint: '恢复与复盘：恢复数据源未接入，此处只呈现已发生的影响与核验记录。' },
}

const ZONED = /(Z|[+-]\d{2}:?\d{2})$/

/** Naive timestamps are Beijing wall time; zoned ones (system timestamps such as review time) are converted to it. */
export function toBeijing(iso: string): string {
  if (!ZONED.test(iso)) return iso
  const ms = Date.parse(iso)
  if (Number.isNaN(ms)) return iso
  return new Date(ms + 8 * 3600_000).toISOString().slice(0, 19)
}

export function fmtTime(iso: string | null | undefined, withDate = true): string {
  if (!iso) return '—'
  const s = toBeijing(iso).replace('T', ' ')
  return withDate ? s.slice(0, 16) : s.slice(11, 16)
}

export function fmtNum(v: number | null | undefined, digits = 0): string {
  if (v == null || Number.isNaN(v)) return '—'
  if (Math.abs(v) < 1 && v !== 0 && digits === 0) return v.toFixed(2)
  return v.toLocaleString('zh-CN', { maximumFractionDigits: digits, minimumFractionDigits: digits })
}

export function hourFloor(iso: string): string {
  return iso.slice(0, 13) + ':00:00'
}

export function addHours(iso: string, hours: number): string {
  const d = new Date(iso.slice(0, 19) + 'Z')
  d.setUTCHours(d.getUTCHours() + hours)
  return d.toISOString().slice(0, 19)
}

export function hoursBetween(a: string, b: string): number {
  return Math.round((Date.parse(b.slice(0, 19) + 'Z') - Date.parse(a.slice(0, 19) + 'Z')) / 3_600_000)
}

export function errorText(e: unknown): string {
  if (e && typeof e === 'object') {
    const detail = (e as { detail?: { message?: string; error_code?: string } }).detail
    if (detail?.message) return detail.error_code ? `${detail.message}（${detail.error_code}）` : detail.message
    const msg = (e as { message?: string }).message
    if (msg) return msg
  }
  return String(e)
}
