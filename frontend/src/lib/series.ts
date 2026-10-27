import type { MetricPoint } from '../api/types'
import { fmtTime } from './format'

export type SeriesData = Array<[string, number | null]>

export function seriesOf(items: MetricPoint[] | undefined, metricId: string, province?: string): SeriesData {
  return (items || [])
    .filter((p) => p.metric_id === metricId && (!province || p.province_code === province))
    .sort((a, b) => a.hour_bj.localeCompare(b.hour_bj))
    .map((p) => [p.hour_bj, p.value])
}

export function valueAt(data: SeriesData, hour: string | null): number | null {
  if (!hour) return null
  const hit = data.find(([t]) => t.slice(0, 13) === hour.slice(0, 13))
  return hit ? hit[1] : null
}

/** Mean of observed values in the real-time window [t - hours, t) for each point; null when the window is empty. */
export function rollingMean(data: SeriesData, hours: number): SeriesData {
  const ms = data.map(([t, v]) => [Date.parse(t.slice(0, 19) + 'Z'), v] as const)
  return data.map(([t], i) => {
    const end = ms[i][0]
    const win = ms.filter(([m, v]) => v != null && m < end && m >= end - hours * 3_600_000).map(([, v]) => v as number)
    return [t, win.length ? Number((win.reduce((a, b) => a + b, 0) / win.length).toFixed(3)) : null]
  })
}

export function describeSeries(name: string, data: SeriesData, unit = ''): string {
  const known = data.filter(([, v]) => v != null) as Array<[string, number]>
  if (!known.length) return `${name}：无观测值`
  const peak = known.reduce((a, b) => (b[1] > a[1] ? b : a))
  const last = known[known.length - 1]
  const u = unit ? ` ${unit}` : ''
  const n = (v: number) => (Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) < 10 ? 2 : 1))
  return `${name}：${known.length} 个有观测的小时，峰值 ${n(peak[1])}${u}（${fmtTime(peak[0])}），最新 ${n(last[1])}${u}（${fmtTime(last[0])}）`
}

export const COLORS = {
  obs: '#0F9CA8',
  accent: '#2563EB',
  attn: '#E98A24',
  muted: '#94A3B8',
  danger: '#D14343',
  violet: '#7C3AED',
}
