<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { locateTrackTime, type TyphoonOverlay } from '../lib/doksuri'
import { fmtTime, provinceName } from '../lib/format'

const props = withDefaults(
  defineProps<{
    values: Record<string, number | null | undefined>
    selected?: string | null
    label?: string
    unit?: string | null
    typhoon?: TyphoonOverlay
    metricTime?: string
    initialBasemap?: 'plain' | 'esa'
    height?: number
    compact?: boolean
    referenceOnly?: boolean
  }>(),
  { selected: null, label: '数值', unit: '', initialBasemap: 'plain', height: 420, compact: false },
)
const emit = defineEmits<{ (e: 'select', code: string | null): void }>()

type Basemap = 'plain' | 'esa' | 'tianditu'

const el = ref<HTMLDivElement | null>(null)
const fallback = ref(false)
const basemap = ref<Basemap>('plain')
const sourceNote = ref('')
const TIANDITU_TK = String(import.meta.env.VITE_TIANDITU_TK || '').trim()

let map: L.Map | null = null
let geoLayer: L.GeoJSON | null = null
let typhoonLayer: L.LayerGroup | null = null
let gridLayer: L.LayerGroup | null = null
let metricMarker: L.CircleMarker | null = null
let geoData: GeoJSON.FeatureCollection | null = null
let tileLayers: L.TileLayer[] = []
let resizeObserver: ResizeObserver | null = null

const entries = computed(() =>
  Object.entries(props.values || {})
    .filter(([code]) => code !== 'ALL')
    .sort((a, b) => Number(b[1] ?? -1) - Number(a[1] ?? -1)),
)
const maxValue = computed(() => Math.max(1, ...entries.value.map(([, v]) => Number(v) || 0)))

function colorFor(value: number | null | undefined) {
  if (value == null || Number.isNaN(Number(value))) return '#1a2230'
  const t = Math.min(1, Math.max(0, Number(value) / maxValue.value))
  const from = [24, 52, 68]
  const to = [45, 212, 191]
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

function styleFeature(feature?: GeoJSON.Feature): L.PathOptions {
  const code = String(feature?.properties?.code || '')
  const selected = !!code && code === props.selected
  return {
    fillColor: colorFor(props.values[code]),
    fillOpacity: basemap.value === 'plain' ? 0.92 : props.typhoon ? 0.3 : 0.52,
    color: selected ? '#7dd3fc' : '#42556b',
    weight: selected ? 2.4 : 1,
    opacity: 1,
  }
}

function display(code: string) {
  const v = props.values?.[code]
  return v == null ? '无数据' : `${v}${props.unit ? ` ${props.unit}` : ''}`
}

function bindFeature(feature: GeoJSON.Feature, layer: L.Layer) {
  const code = String(feature.properties?.code || '')
  const name = String(feature.properties?.name || provinceName(code))
  layer.bindTooltip(() => props.referenceOnly ? name : `${name}　${props.label}：${display(code)}`, { sticky: true, className: 'province-tip' })
  layer.on({
    click: () => { if (!props.referenceOnly) emit('select', code === props.selected ? null : code || null) },
    mouseover: (e) => (e.target as L.Path).setStyle({ weight: 2, color: '#7dd3fc' }),
    mouseout: (e) => (e.target as L.Path).setStyle(styleFeature(feature)),
  })
}

function refreshLayer() {
  if (!map || !geoData) return
  if (geoLayer) map.removeLayer(geoLayer)
  geoLayer = L.geoJSON(geoData as GeoJSON.GeoJsonObject, {
    style: (f) => styleFeature(f as GeoJSON.Feature),
    onEachFeature: (f, layer) => bindFeature(f as GeoJSON.Feature, layer),
  }).addTo(map)
}

const TYPHOON_PANE = 'typhoonOverlay'
const SYMBOL_PANE = 'typhoonSymbols'
const GRID_PANE = 'mapGrid'
const TRACK_COLOR = '#5eead4'
const PATH_OUTLINE = '#06080c'
const METRIC_COLOR = '#c084fc'
const metricPosition = computed(() =>
  props.typhoon && props.metricTime ? locateTrackTime(props.typhoon.track, props.metricTime) : undefined,
)

function drawGrid() {
  gridLayer?.remove()
  gridLayer = null
  if (!map || !props.typhoon || basemap.value !== 'plain') return

  const lines = L.layerGroup()
  const options = { pane: GRID_PANE, color: '#334155', opacity: 0.38, weight: 1, interactive: false }
  for (let lat = -5; lat <= 55; lat += 5) {
    L.polyline([[lat, 80], [lat, 165]], options).addTo(lines)
  }
  for (let lon = 80; lon <= 165; lon += 5) {
    L.polyline([[-5, lon], [55, lon]], options).addTo(lines)
  }
  gridLayer = lines.addTo(map)
}

function drawTyphoon() {
  if (!map) return
  typhoonLayer?.remove()
  typhoonLayer = null
  const overlay = props.typhoon
  if (!overlay) return

  const group = L.layerGroup()
  const lineOptions = { pane: TYPHOON_PANE, interactive: false }
  const symbolOptions = { pane: SYMBOL_PANE, interactive: false, keyboard: false }
  for (const line of overlay.warnings) {
    L.polyline(line.points, { ...lineOptions, color: PATH_OUTLINE, opacity: 0.9, weight: 4, dashArray: line.dash }).addTo(group)
    L.polyline(line.points, { ...lineOptions, color: line.color, weight: 2, dashArray: line.dash, className: `warning-line-${line.hours}` }).addTo(group)
    const [north, south] = line.points
    L.marker([(north[0] + south[0]) / 2, north[1]], {
      ...symbolOptions,
      icon: L.divIcon({
        className: `warning-label warning-label-${line.hours}`,
        html: `${line.hours}h`,
        iconSize: [31, 20],
        iconAnchor: [15, 10],
      }),
    }).addTo(group)
  }

  const points = overlay.track.map(({ lat, lon }) => L.latLng(lat, lon))
  if (points.length > 1) {
    L.polyline(points, { ...lineOptions, color: PATH_OUTLINE, weight: 5, smoothFactor: 0 }).addTo(group)
    L.polyline(points, { ...lineOptions, color: TRACK_COLOR, weight: 2.5, smoothFactor: 0, className: 'doksuri-track' }).addTo(group)
    for (const index of [8, 18, 27]) {
      const [from, to] = [points[index], points[index + 1]]
      if (!from || !to) continue
      const projection = L.CRS.EPSG3857
      const delta = projection.project(to).subtract(projection.project(from))
      const angle = Math.atan2(-delta.y, delta.x) * 180 / Math.PI
      const center = projection.unproject(projection.project(from).add(delta.divideBy(2)))
      L.marker(center, {
        ...symbolOptions,
        icon: L.divIcon({
          className: 'track-direction',
          html: `<span aria-hidden="true" style="transform: rotate(${angle}deg)">➤</span>`,
          iconSize: [18, 18],
          iconAnchor: [9, 9],
        }),
      }).addTo(group)
    }
  }

  overlay.track.forEach((point, index) => {
    const endpoint = index === 0 || index === points.length - 1
    L.circleMarker(points[index], {
      pane: TYPHOON_PANE, radius: endpoint ? 4.5 : 2.7, color: PATH_OUTLINE, weight: 1.2,
      fillColor: TRACK_COLOR, fillOpacity: 1, className: 'doksuri-point',
    }).bindTooltip(
      `杜苏芮 · ${fmtTime(point.time)} 北京时间<br>${point.lat.toFixed(1)}°N，${point.lon.toFixed(1)}°E · 最大地面风速 ${point.wind} m/s`,
      { direction: 'top', className: 'province-tip' },
    ).addTo(group)
  })
  typhoonLayer = group.addTo(map)
}

function drawMetricTime() {
  metricMarker?.remove()
  metricMarker = null
  const position = metricPosition.value
  if (!map || !position) return
  const { from, to, fraction } = position
  // Interpolate in the same projection as the displayed polyline.
  const projection = L.CRS.EPSG3857
  const start = projection.project(L.latLng(from.lat, from.lon))
  const end = projection.project(L.latLng(to.lat, to.lon))
  const point = projection.unproject(start.add(end.subtract(start).multiplyBy(fraction)))
  metricMarker = L.circleMarker(point, {
    pane: TYPHOON_PANE, radius: 7.5, color: PATH_OUTLINE, weight: 2, interactive: false,
    fillColor: METRIC_COLOR, fillOpacity: 1, className: 'doksuri-metric-point',
  }).addTo(map)
}

function fitMap() {
  if (!map) return
  if (props.typhoon) {
    // Cover the full storm path and both fixed warning lines, even in strict replay.
    map.fitBounds([[13, 110], [34, 132.6]], { paddingTopLeft: [22, 38], paddingBottomRight: [22, 30] })
    return
  }
  const bounds = geoLayer?.getBounds()
  if (bounds?.isValid()) map.fitBounds(bounds.pad(0.04))
}

function esaTiles() {
  return [
    L.tileLayer('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg', {
      attribution: 'Sentinel-2 cloudless 2024 by EOX (Copernicus Sentinel data, ESA)',
      maxZoom: 16,
      maxNativeZoom: 13,
    }),
  ]
}

function tiandituTiles(tk: string) {
  const url = (layer: 'img' | 'cia') =>
    `https://t{s}.tianditu.gov.cn/${layer}_w/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=${layer}&STYLE=default&TILEMATRIXSET=w&FORMAT=tiles&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}&tk=${encodeURIComponent(tk)}`
  const common: L.TileLayerOptions = { subdomains: '01234567', maxZoom: 18 }
  return [L.tileLayer(url('img'), { ...common, attribution: '&copy; 天地图' }), L.tileLayer(url('cia'), common)]
}

function applyBasemap(id: Basemap) {
  if (!map) return
  if (id === 'tianditu' && !TIANDITU_TK) return
  if (id === basemap.value) return
  for (const layer of tileLayers) map.removeLayer(layer)
  tileLayers = id === 'tianditu' ? tiandituTiles(TIANDITU_TK) : id === 'esa' ? esaTiles() : []
  sourceNote.value = ''
  let errors = 0
  for (const layer of tileLayers) {
    layer.on('tileerror', () => {
      errors += 1
      if (errors < 4 || basemap.value !== id) return
      applyBasemap('plain')
      sourceNote.value = id === 'esa' ? '影像底图不可达，已切回简图' : '天地图加载失败，已切回简图'
    })
    layer.addTo(map)
  }
  basemap.value = id
  geoLayer?.setStyle((f) => styleFeature(f as GeoJSON.Feature))
  drawGrid()
}

async function initMap() {
  if (!el.value) return
  try {
    const res = await fetch('/geo/china_provinces.json')
    if (!res.ok) throw new Error('geo missing')
    geoData = await res.json()
    if (!el.value) return
    map = L.map(el.value, { zoomControl: !props.compact, attributionControl: true, minZoom: 3, maxZoom: 12, zoomSnap: props.compact ? 1 : 0.25 })
    map.createPane(GRID_PANE).style.zIndex = '350'
    map.createPane(TYPHOON_PANE).style.zIndex = '450'
    const symbols = map.createPane(SYMBOL_PANE)
    symbols.style.zIndex = '455'
    symbols.style.pointerEvents = 'none'
    refreshLayer()
    drawTyphoon()
    fitMap()
    if (props.initialBasemap === 'esa') applyBasemap('esa')
    else drawGrid()
    if (!props.compact) L.control.scale({ imperial: false }).addTo(map)
    drawMetricTime()
    resizeObserver = new ResizeObserver(() => map?.invalidateSize())
    resizeObserver.observe(el.value)
  } catch {
    fallback.value = true
  }
}

function onRowKey(e: KeyboardEvent, code: string) {
  if (e.key === 'Enter' || e.key === ' ') {
    e.preventDefault()
    emit('select', code === props.selected ? null : code)
  }
}

onMounted(initMap)
watch(() => props.values, refreshLayer, { deep: true })
watch(() => props.typhoon, (overlay, previous) => {
  drawTyphoon()
  drawMetricTime()
  if (!!overlay !== !!previous) {
    drawGrid()
    geoLayer?.setStyle((f) => styleFeature(f as GeoJSON.Feature))
    fitMap()
  }
})
watch(() => props.metricTime, drawMetricTime)
watch(
  () => props.selected,
  () => geoLayer?.setStyle((f) => styleFeature(f as GeoJSON.Feature)),
)
onUnmounted(() => {
  resizeObserver?.disconnect()
  map?.remove()
  map = null
})
</script>

<template>
  <div class="map-wrap" :style="{ '--map-height': `${height}px` }">
    <div v-if="fallback" class="fallback">
      <p class="note attn">{{ referenceOnly ? '本地地图暂时不可用。' : '本地省界数据不可用，地图降级为省份表。可用方向键与回车选择省份。' }}</p>
      <div v-if="!referenceOnly" class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>省份</th>
              <th>{{ label }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="[code] in entries"
              :key="code"
              class="clickable"
              tabindex="0"
              :aria-selected="code === selected"
              @click="emit('select', code === selected ? null : code)"
              @keydown="onRowKey($event, code)"
            >
              <td>{{ provinceName(code) }}</td>
              <td class="num">{{ display(code) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>
    <div v-show="!fallback" class="map-shell">
      <div ref="el" class="map" role="application" :aria-label="referenceOnly ? '杜苏芮历史路径及警戒线地图' : `省级${label}地图，点击省份可筛选`"></div>
      <div v-if="!compact" class="seg basemap" role="group" aria-label="底图">
        <button type="button" :class="{ on: basemap === 'plain' }" :aria-pressed="basemap === 'plain'" @click="applyBasemap('plain')">简图</button>
        <button type="button" :class="{ on: basemap === 'esa' }" :aria-pressed="basemap === 'esa'" title="2024 年 Sentinel-2 影像底图" @click="applyBasemap('esa')">影像</button>
        <button
          type="button"
          :class="{ on: basemap === 'tianditu' }"
          :aria-pressed="basemap === 'tianditu'"
          :disabled="!TIANDITU_TK"
          :title="TIANDITU_TK ? '天地图影像' : '在 frontend/.env 设置 VITE_TIANDITU_TK 后可用'"
          @click="applyBasemap('tianditu')"
        >
          天地图
        </button>
      </div>
      <div v-if="sourceNote" class="source-note" role="status">{{ sourceNote }}</div>
    </div>
    <div v-if="!fallback" class="legend" aria-label="地图图例">
      <span class="swatch"></span>
      <span>{{ label }} 0 → {{ maxValue }}{{ unit ? ` ${unit}` : '' }}</span>
      <span class="nodata">灰色＝无数据</span>
      <div v-if="typhoon" class="typhoon-keys">
        <span v-if="typhoon.track.length"><i class="path-key" aria-hidden="true"></i>杜苏芮历史路径</span>
        <span v-for="line in typhoon.warnings" :key="line.hours" :style="{ color: line.color }">
          <i class="warning-key" :class="{ 'warning-key-short': line.hours === 48 }" aria-hidden="true"></i>{{ line.hours }} 小时警戒线
        </span>
      </div>
    </div>
    <p v-if="!fallback && metricPosition" class="metric-time-caption small">
      <span class="metric-time-dot" aria-hidden="true"></span>
      <span>指标时刻 <strong class="num">{{ fmtTime(metricTime) }}</strong><template v-if="metricPosition.fraction">（插值）</template></span>
    </p>
    <ul class="sr-only" aria-label="省份数值">
      <li v-for="[code] in entries" :key="code">{{ provinceName(code) }}：{{ display(code) }}</li>
    </ul>
  </div>
</template>

<style scoped>
.map-wrap {
  width: 100%;
}
.map-shell {
  position: relative;
  height: var(--map-height);
  overflow: hidden;
  border: 1px solid var(--line);
  border-radius: calc(var(--panel-radius) - 2px);
}
.map {
  width: 100%;
  height: 100%;
  background: #080d16;
}
.metric-time-caption {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin: 7px 0 0;
  color: v-bind(METRIC_COLOR);
}
.metric-time-dot {
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 8px color-mix(in oklab, currentColor 60%, transparent);
}
.basemap {
  --control-selected: var(--obs-soft);
  --control-selected-text: var(--obs);
  --line-active: var(--obs);
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 500;
  background: var(--hud-bg);
  border-color: var(--line-strong);
  backdrop-filter: blur(var(--hud-blur));
  -webkit-backdrop-filter: blur(var(--hud-blur));
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.55);
}
.basemap button {
  min-height: 26px;
  padding-inline: 10px;
  font-size: 12px;
}
.legend {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 10px;
  padding: 8px 0 0;
  font-size: 12px;
  color: var(--muted);
}
.swatch {
  width: 56px;
  height: 8px;
  border-radius: 999px;
  background: linear-gradient(90deg var(--in-oklab), #183444, #2dd4bf);
}
.typhoon-keys {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
}
.typhoon-keys span {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.path-key,
.warning-key {
  width: 18px;
  border-top: 2px dashed currentColor;
}
.path-key {
  border-top: 2px solid v-bind(TRACK_COLOR);
}
.warning-key-short {
  border-top-style: dotted;
}
.source-note {
  position: absolute;
  top: 44px;
  right: 10px;
  z-index: 500;
  max-width: 240px;
  padding: 6px 8px;
  border-radius: 6px;
  background: var(--attn-soft);
  color: var(--attn);
  font-size: 12px;
}
.fallback {
  height: var(--map-height);
  overflow: auto;
}
</style>

<style>
.warning-label {
  border: 1px solid currentColor;
  border-radius: 5px;
  background: rgba(9, 12, 18, 0.84);
  backdrop-filter: blur(6px);
  font-size: 11px;
  font-weight: 700;
  line-height: 18px;
  text-align: center;
}
.warning-label-24 { color: #fb7185; }
.warning-label-48 { color: #fbbf24; }
.track-direction span {
  display: block;
  color: #5eead4;
  font-size: 17px;
  line-height: 18px;
  text-align: center;
  -webkit-text-stroke: 1px #06080c;
  paint-order: stroke fill;
}
.province-tip {
  background: rgba(14, 18, 26, 0.92) !important;
  color: var(--text) !important;
  border: 1px solid var(--line-strong) !important;
  border-radius: 6px !important;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.5) !important;
}
.leaflet-container {
  font-family: inherit;
}
.leaflet-container .leaflet-control-attribution {
  background: rgba(14, 18, 26, 0.78);
  color: var(--muted);
  font-size: 10px !important;
}
.leaflet-container .leaflet-control-attribution a {
  color: var(--accent);
}
.leaflet-container .leaflet-control-scale-line,
.leaflet-container .leaflet-control-zoom a {
  background: var(--hud-bg);
  color: var(--text);
  border-color: var(--line-strong);
  text-shadow: none;
  backdrop-filter: blur(10px);
}
.leaflet-container .leaflet-control-zoom.leaflet-bar {
  border: 1px solid var(--line-strong);
  border-radius: var(--control-radius);
  overflow: hidden;
  box-shadow: 0 8px 20px rgba(0, 0, 0, 0.45);
}
.leaflet-container .leaflet-control-zoom a:first-child {
  border-radius: 2px 8px 0 0;
}
.leaflet-container .leaflet-control-zoom a:last-child {
  border-radius: 0 0 2px 2px;
}
.leaflet-container .leaflet-control-zoom a:hover:not(.leaflet-disabled) {
  background: var(--control-hover);
  color: var(--line-active);
}
.leaflet-container .leaflet-control-zoom a.leaflet-disabled {
  color: var(--faint);
}
.leaflet-container .leaflet-control-zoom a:focus-visible {
  outline-offset: -3px;
}
</style>
