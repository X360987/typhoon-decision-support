<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { provinceName } from '../lib/format'

export interface TrackPoint {
  lat: number
  lon: number
  label: string
}

const props = withDefaults(
  defineProps<{
    values: Record<string, number | null | undefined>
    selected?: string | null
    label?: string
    unit?: string | null
    track?: TrackPoint[]
    trackLabel?: string
    height?: number
    compact?: boolean
  }>(),
  { selected: null, label: '数值', unit: '', track: () => [], trackLabel: '预报路径', height: 420, compact: false },
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
let trackLayer: L.LayerGroup | null = null
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
  if (value == null || Number.isNaN(Number(value))) return '#EEF1F5'
  const t = Math.min(1, Math.max(0, Number(value) / maxValue.value))
  const from = [222, 242, 244]
  const to = [15, 156, 168]
  const c = from.map((f, i) => Math.round(f + (to[i] - f) * t))
  return `rgb(${c[0]},${c[1]},${c[2]})`
}

function styleFeature(feature?: GeoJSON.Feature): L.PathOptions {
  const code = String(feature?.properties?.code || '')
  const hasValue = code in (props.values || {})
  const selected = !!code && code === props.selected
  return {
    fillColor: hasValue ? colorFor(props.values[code]) : '#F4F6F8',
    fillOpacity: basemap.value === 'plain' ? 0.9 : 0.55,
    color: selected ? '#2563EB' : '#9AA8B8',
    weight: selected ? 2.4 : 0.8,
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
  layer.bindTooltip(() => `${name}　${props.label}：${display(code)}`, { sticky: true, className: 'province-tip' })
  layer.on({
    click: () => emit('select', code === props.selected ? null : code || null),
    mouseover: (e) => (e.target as L.Path).setStyle({ weight: 2, color: '#2563EB' }),
    mouseout: (e) => geoLayer?.resetStyle(e.target),
  })
}

function refreshLayer() {
  if (!map || !geoData) return
  if (geoLayer) map.removeLayer(geoLayer)
  geoLayer = L.geoJSON(geoData as GeoJSON.GeoJsonObject, {
    style: (f) => styleFeature(f as GeoJSON.Feature),
    onEachFeature: (f, layer) => bindFeature(f as GeoJSON.Feature, layer),
  }).addTo(map)
  drawTrack()
}

function drawTrack() {
  if (!map) return
  if (trackLayer) map.removeLayer(trackLayer)
  trackLayer = null
  const pts = props.track.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon))
  if (!pts.length) return
  const group = L.layerGroup()
  L.polyline(
    pts.map((p) => [p.lat, p.lon] as L.LatLngTuple),
    { color: '#E98A24', weight: 2, dashArray: '6 6' },
  ).addTo(group)
  for (const p of pts) {
    L.circleMarker([p.lat, p.lon], { radius: 4, color: '#E98A24', fillColor: '#fff', fillOpacity: 1, weight: 2 })
      .bindTooltip(p.label)
      .addTo(group)
  }
  trackLayer = group.addTo(map)
}

function esaTiles() {
  return [
    L.tileLayer('https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2024_3857/default/g/{z}/{y}/{x}.jpg', {
      attribution: 'Sentinel-2 cloudless by EOX (Copernicus Sentinel data, ESA)',
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
  for (const layer of tileLayers) map.removeLayer(layer)
  tileLayers = id === 'tianditu' ? tiandituTiles(TIANDITU_TK) : id === 'esa' ? esaTiles() : []
  sourceNote.value = ''
  let errors = 0
  for (const layer of tileLayers) {
    layer.on('tileerror', () => {
      errors += 1
      if (errors >= 4) sourceNote.value = id === 'esa' ? '影像底图不可达，已保留本地省界简图' : '天地图加载失败，请核对密钥与域名白名单'
    })
    layer.addTo(map)
  }
  basemap.value = id
  geoLayer?.setStyle((f) => styleFeature(f as GeoJSON.Feature))
  geoLayer?.bringToFront()
  if (trackLayer) drawTrack()
}

async function initMap() {
  if (!el.value) return
  try {
    const res = await fetch('/geo/china_provinces.json')
    if (!res.ok) throw new Error('geo missing')
    geoData = await res.json()
    map = L.map(el.value, { zoomControl: !props.compact, attributionControl: true, minZoom: 3, maxZoom: 12 })
    refreshLayer()
    const bounds = geoLayer?.getBounds()
    if (bounds?.isValid()) map.fitBounds(bounds.pad(0.04))
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
watch(() => props.track, drawTrack, { deep: true })
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
  <div class="map-wrap" :style="{ height: `${height}px` }">
    <div v-if="fallback" class="fallback">
      <p class="note attn">本地省界数据不可用，地图降级为省份表。可用方向键与回车选择省份。</p>
      <div class="table-wrap">
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
      <div ref="el" class="map" role="application" :aria-label="`省级${label}地图，点击省份可筛选`"></div>
      <div v-if="!compact" class="basemap" role="group" aria-label="底图">
        <button type="button" :class="{ on: basemap === 'plain' }" @click="applyBasemap('plain')">简图</button>
        <button type="button" :class="{ on: basemap === 'esa' }" @click="applyBasemap('esa')">影像</button>
        <button
          type="button"
          :class="{ on: basemap === 'tianditu' }"
          :disabled="!TIANDITU_TK"
          :title="TIANDITU_TK ? '天地图影像' : '在 frontend/.env 设置 VITE_TIANDITU_TK 后可用'"
          @click="applyBasemap('tianditu')"
        >
          天地图
        </button>
      </div>
      <div class="legend">
        <span class="swatch"></span>
        <span>{{ label }} 0 → {{ maxValue }}{{ unit ? ` ${unit}` : '' }}</span>
        <span v-if="track.length" class="track-key">┅ {{ trackLabel }}</span>
        <span class="nodata">灰色＝无数据</span>
      </div>
      <div v-if="sourceNote" class="source-note">{{ sourceNote }}</div>
    </div>
    <ul class="sr-only" aria-label="省份数值">
      <li v-for="[code] in entries" :key="code">{{ provinceName(code) }}：{{ display(code) }}</li>
    </ul>
  </div>
</template>

<style scoped>
.map-wrap {
  position: relative;
  width: 100%;
}
.map-shell,
.map {
  width: 100%;
  height: 100%;
}
.map {
  background: #e8f0f6;
}
.basemap {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 500;
  display: flex;
  border: 1px solid var(--line-strong);
  border-radius: 6px;
  overflow: hidden;
  background: #fff;
}
.basemap button {
  padding: 3px 10px;
  border: 0;
  border-right: 1px solid var(--line);
  background: #fff;
  font-size: 12px;
  cursor: pointer;
}
.basemap button:last-child {
  border-right: 0;
}
.basemap button.on {
  background: var(--accent);
  color: #fff;
}
.basemap button:disabled {
  color: var(--faint);
  cursor: not-allowed;
}
.legend {
  position: absolute;
  left: 10px;
  bottom: 10px;
  z-index: 500;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 5px 10px;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.92);
  font-size: 12px;
  color: var(--muted);
  pointer-events: none;
}
.swatch {
  width: 56px;
  height: 8px;
  border-radius: 2px;
  background: linear-gradient(90deg, #def2f4, #0f9ca8);
}
.track-key {
  color: var(--attn);
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
  color: #8a4b0f;
  font-size: 12px;
}
.fallback {
  height: 100%;
  overflow: auto;
}
</style>

<style>
.province-tip {
  background: #fff !important;
  color: #102a43 !important;
  border: 1px solid #d4dbe5 !important;
  box-shadow: 0 2px 8px rgba(16, 42, 67, 0.08) !important;
}
.leaflet-container {
  font-family: inherit;
}
.leaflet-control-attribution {
  font-size: 10px !important;
}
</style>
