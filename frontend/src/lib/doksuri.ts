import { toBeijing } from './format'

export interface TrackPoint {
  lat: number
  lon: number
  time: string
  wind: number
}

export interface TyphoonOverlay {
  track: TrackPoint[]
  warnings: { hours: 24 | 48; points: [number, number][]; color: string; dash: string }[]
}

export const DOKSURI_TRACK_SOURCE = 'https://www.hko.gov.hk/en/publica/tc/tc2023/six_hrly_data_doksuri.html'
export const WARNING_LINES_SOURCE = 'https://www.weather.com.cn/typhoon/tfzs/04/397397.shtml'

// 香港天文台 2305 号最佳路径。首条记录为 2023-07-20 12:00 UTC，以下每行相隔 6 小时。
// 列顺序为北纬、东经和估计最大地面风速（m/s）。
const firstTime = Date.UTC(2023, 6, 20, 12)
const observations = [
  [13.0, 132.6, 13],
  [13.4, 132.4, 13],
  [13.8, 132.2, 16],
  [14.0, 132.0, 16],
  [14.3, 131.8, 16],
  [14.4, 131.5, 18],
  [14.5, 131.2, 18],
  [14.5, 130.7, 21],
  [14.6, 130.2, 23],
  [14.7, 129.7, 25],
  [14.7, 129.0, 28],
  [14.9, 128.4, 31],
  [15.1, 127.7, 36],
  [15.2, 127.0, 39],
  [15.3, 126.6, 43],
  [15.7, 126.3, 49],
  [16.5, 125.8, 52],
  [16.9, 125.1, 54],
  [17.6, 124.6, 59],
  [18.3, 123.7, 59],
  [18.8, 122.7, 57],
  [19.0, 121.5, 57],
  [18.9, 121.3, 54],
  [19.3, 121.0, 52],
  [19.6, 120.6, 46],
  [20.0, 120.1, 46],
  [20.8, 119.8, 43],
  [21.1, 119.3, 46],
  [21.8, 119.2, 52],
  [22.8, 119.0, 52],
  [24.2, 118.8, 46],
  [25.5, 118.2, 33],
  [27.1, 117.6, 25],
  [28.6, 117.3, 21],
  [30.0, 116.5, 16],
] as const

const warnings: TyphoonOverlay['warnings'] = [
  { hours: 48, points: [[34, 132], [22, 132], [15, 125], [15, 110]], color: '#fbbf24', dash: '4 7' },
  { hours: 24, points: [[34, 127], [22, 127], [15, 110]], color: '#fb7185', dash: '10 6' },
]

export const DOKSURI_OVERLAY: TyphoonOverlay = {
  warnings,
  track: observations.map(([lat, lon, wind], i) => ({
    lat,
    lon,
    wind,
    time: new Date(firstTime + i * 6 * 60 * 60 * 1000).toISOString(),
  })),
}

export const DOKSURI_WARNINGS_ONLY: TyphoonOverlay = { warnings, track: [] }

/** Find the metric time on the ordered historical track, without extrapolating. */
export function locateTrackTime(track: readonly TrackPoint[], metricTime: string) {
  const time = Date.parse(`${toBeijing(metricTime)}+08:00`)
  const index = track.findIndex((point) => Date.parse(point.time) >= time)
  if (index < 0) return undefined

  const to = track[index]
  const toTime = Date.parse(to.time)
  if (toTime === time) return { from: to, to, fraction: 0 }
  if (index === 0) return undefined

  const from = track[index - 1]
  const fromTime = Date.parse(from.time)
  return { from, to, fraction: (time - fromTime) / (toTime - fromTime) }
}
