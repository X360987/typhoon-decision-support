<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { echarts } from '../lib/echarts'

export interface ChartAxis {
  name?: string
  lane?: number
  right?: boolean
  max?: number
  min?: number
}

export interface ChartSeries {
  name: string
  data: Array<[string, number | null]>
  type?: 'line' | 'bar' | 'scatter'
  color?: string
  dashed?: boolean
  axis?: number
  area?: boolean
  stack?: string
  symbol?: boolean
}

export interface ChartMarker {
  time: string
  label: string
  color?: string
}

const props = withDefaults(
  defineProps<{
    series: ChartSeries[]
    axes?: ChartAxis[]
    lanes?: number
    cursor?: string | null
    cursorLabel?: string
    markers?: ChartMarker[]
    xMin?: string
    xMax?: string
    height?: number
    daily?: boolean
    summary: string
    ariaLabel?: string
  }>(),
  { axes: () => [{}], lanes: 1, cursor: null, cursorLabel: '', markers: () => [], height: 280, ariaLabel: '时间序列图' },
)

const emit = defineEmits<{ (e: 'pick', time: string): void }>()

const el = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null
let observer: ResizeObserver | null = null

const hasData = computed(() => props.series.some((s) => s.data.some(([, v]) => v != null)))

function toMs(iso: string) {
  return Date.parse(iso.slice(0, 19) + 'Z')
}

function fmtAxis(ms: number) {
  const d = new Date(ms)
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0')
  const dd = String(d.getUTCDate()).padStart(2, '0')
  const hh = String(d.getUTCHours()).padStart(2, '0')
  return hh === '00' ? `${mm}-${dd}` : `${hh}:00`
}

function fmtTip(ms: number) {
  return new Date(ms).toISOString().slice(5, 16).replace('T', ' ')
}

function build() {
  const theme = getComputedStyle(document.documentElement)
  const muted = theme.getPropertyValue('--muted').trim()
  const text = theme.getPropertyValue('--text').trim()
  const secondary = theme.getPropertyValue('--text-secondary').trim()
  const line = theme.getPropertyValue('--line').trim()
  const strongLine = theme.getPropertyValue('--line-strong').trim()
  const accent = theme.getPropertyValue('--accent').trim()
  const cursorLine = theme.getPropertyValue('--line-active').trim()
  const lanes = Math.max(1, props.lanes)
  const top = 54
  const bottom = 30
  const gap = lanes > 1 ? 32 : 0
  const usable = props.height - top - bottom - gap * (lanes - 1)
  const laneH = usable / lanes
  const grid = Array.from({ length: lanes }, (_, i) => ({
    left: 56,
    right: props.axes.some((a) => a.right) ? 56 : 22,
    top: top + i * (laneH + gap),
    height: laneH,
  }))
  const xMin = props.xMin ? toMs(props.xMin) : undefined
  const xMax = props.xMax ? toMs(props.xMax) : undefined
  const xAxis = grid.map((_, i) => ({
    type: 'time' as const,
    gridIndex: i,
    min: xMin,
    max: xMax,
    minInterval: props.daily ? 86_400_000 : undefined,
    axisLabel: {
      show: i === lanes - 1,
      color: muted,
      formatter: props.daily ? (ms: number) => new Date(ms).toISOString().slice(5, 10) : fmtAxis,
      hideOverlap: true,
    },
    axisLine: { lineStyle: { color: strongLine } },
    axisTick: { show: i === lanes - 1, lineStyle: { color: strongLine } },
    splitLine: { show: false },
  }))
  const yAxis = props.axes.map((a) => ({
    type: 'value' as const,
    gridIndex: a.lane ?? 0,
    name: a.name,
    nameTextStyle: { color: muted, fontSize: 11, align: a.right ? ('right' as const) : ('left' as const) },
    position: a.right ? ('right' as const) : ('left' as const),
    min: a.min,
    max: a.max,
    splitNumber: lanes > 1 ? 2 : 4,
    axisLabel: { color: muted, fontSize: 11 },
    splitLine: { show: !a.right, lineStyle: { color: line, type: 'dashed' as const } },
  }))
  const series: Array<Record<string, unknown>> = props.series.map((s) => {
    const axisIdx = s.axis ?? 0
    const lane = props.axes[axisIdx]?.lane ?? 0
    const data = s.data.map(([t, v]) => [toMs(t), v])
    const common = {
      name: s.name,
      xAxisIndex: lane,
      yAxisIndex: axisIdx,
      data,
      itemStyle: { color: s.color },
    }
    if (s.type === 'bar')
      return {
        ...common,
        type: 'bar',
        stack: s.stack,
        barMaxWidth: 10,
        itemStyle: { color: s.color, opacity: 0.78, borderRadius: [3, 3, 0, 0] },
      }
    if (s.type === 'scatter') return { ...common, type: 'scatter', symbolSize: 9 }
    return {
      ...common,
      type: 'line',
      connectNulls: false,
      showSymbol: s.symbol ?? false,
      symbolSize: 5,
      lineStyle: { color: s.color, width: 2, type: s.dashed ? 'dashed' : 'solid' },
      areaStyle: s.area
        ? {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: s.color || accent },
                { offset: 1, color: 'rgba(6, 8, 12, 0)' },
              ],
            },
            opacity: 0.22,
          }
        : undefined,
    }
  })
  const marks = [
    ...(props.cursor ? [{ time: props.cursor, label: props.cursorLabel, color: cursorLine }] : []),
    ...props.markers,
  ]
  for (let lane = 0; lane < lanes; lane++) {
    series.push({
      type: 'line',
      name: `__marks_${lane}`,
      xAxisIndex: lane,
      yAxisIndex: props.axes.findIndex((a) => (a.lane ?? 0) === lane),
      data: [],
      silent: true,
      markLine: {
        symbol: 'none',
        animation: false,
        data: marks.map((m) => ({
          xAxis: toMs(m.time),
          lineStyle: { color: m.color || accent, type: 'solid', width: 1.2 },
          label: { show: lane === 0 && !!m.label, formatter: m.label, color: m.color || accent, position: 'end' as const },
        })),
      },
    })
  }
  return {
    animation: false,
    grid,
    xAxis,
    yAxis,
    series,
    legend: {
      type: 'scroll',
      top: 0,
      left: 0,
      itemWidth: 16,
      itemHeight: 8,
      textStyle: { color: secondary, fontSize: 12 },
      pageTextStyle: { color: muted },
      pageIconColor: accent,
      pageIconInactiveColor: strongLine,
      data: props.series.map((s) => s.name),
    },
    tooltip: {
      trigger: 'axis',
      confine: true,
      backgroundColor: 'rgba(14, 18, 26, 0.92)',
      borderColor: strongLine,
      borderWidth: 1,
      padding: [8, 12],
      extraCssText: 'backdrop-filter: blur(12px); border-radius: 8px; box-shadow: 0 12px 28px rgba(0, 0, 0, 0.55);',
      textStyle: { color: text, fontSize: 12 },
      axisPointer: { type: 'line', lineStyle: { color: strongLine, type: 'dashed' } },
      formatter: (items: unknown) => {
        const list = (Array.isArray(items) ? items : [items]) as Array<{
          seriesName: string
          value: [number, number | null]
          marker: string
        }>
        const shown = list.filter((i) => !i.seriesName.startsWith('__'))
        if (!shown.length) return ''
        const head = props.daily ? new Date(shown[0].value[0]).toISOString().slice(0, 10) : fmtTip(shown[0].value[0])
        return [head, ...shown.map((i) => `${i.marker}${i.seriesName}：${i.value[1] ?? '缺测'}`)].join('<br/>')
      },
    },
  } as echarts.EChartsCoreOption
}

function render() {
  if (!el.value) return
  if (!chart) {
    chart = echarts.init(el.value)
    chart.getZr().on('click', (evt) => {
      if (!chart || props.daily) return
      const point = [evt.offsetX, evt.offsetY]
      for (let lane = 0; lane < props.lanes; lane++) {
        if (chart.containPixel({ gridIndex: lane }, point)) {
          const [ms] = chart.convertFromPixel({ gridIndex: lane }, point) as number[]
          emit('pick', new Date(ms).toISOString().slice(0, 19))
          return
        }
      }
    })
  }
  chart.setOption(build(), true)
}

onMounted(() => {
  render()
  if (el.value) {
    observer = new ResizeObserver(() => chart?.resize())
    observer.observe(el.value)
  }
})

watch(
  () => [props.series, props.cursor, props.markers, props.xMin, props.xMax, props.lanes, props.axes, props.height, props.daily],
  render,
  { deep: true },
)

onBeforeUnmount(() => {
  observer?.disconnect()
  chart?.dispose()
  chart = null
})
</script>

<template>
  <figure class="trend">
    <div ref="el" class="canvas" role="img" :aria-label="`${ariaLabel}：${summary}`" :style="{ height: `${height}px` }"></div>
    <p v-if="!hasData" class="empty muted small">图中无可绘制的观测值。</p>
    <figcaption class="chart-summary">{{ summary }}</figcaption>
  </figure>
</template>

<style scoped>
.trend {
  margin: 0;
  position: relative;
}
.canvas {
  width: 100%;
}
.empty {
  position: absolute;
  top: 40%;
  left: 0;
  right: 0;
  text-align: center;
  pointer-events: none;
}
</style>
