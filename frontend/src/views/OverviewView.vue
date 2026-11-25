<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import AnomalyPanel from '../components/AnomalyPanel.vue'
import ContextGate from '../components/ContextGate.vue'
import MetricCards, { type MetricCardView } from '../components/MetricCards.vue'
import ProvinceMap from '../components/ProvinceMap.vue'
import StatusNote from '../components/StatusNote.vue'
import TimeAxis from '../components/TimeAxis.vue'
import TrendChart, { type ChartSeries } from '../components/TrendChart.vue'
import { useLoader } from '../composables/useLoader'
import { DOKSURI_OVERLAY, DOKSURI_TRACK_SOURCE, DOKSURI_WARNINGS_ONLY, WARNING_LINES_SOURCE } from '../lib/doksuri'
import { PHASE_NAMES, addHours, fmtTime, provinceName } from '../lib/format'
import { COLORS, describeSeries, seriesOf } from '../lib/series'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const router = useRouter()
const mobilePlayback = ref<HTMLElement | null>(null)
const narrowScreen = window.matchMedia('(max-width: 760px)')
const useCompactPlayback = ref(narrowScreen.matches)

function syncPlaybackLayout(event: MediaQueryListEvent) {
  useCompactPlayback.value = event.matches
}

onMounted(() => narrowScreen.addEventListener('change', syncPlaybackLayout))
onUnmounted(() => narrowScreen.removeEventListener('change', syncPlaybackLayout))

const dailyMetrics = [
  { key: 'weibo_count', label: '微博总量', tone: 'obs' },
  { key: 'government_weibo_count', label: '政府部门发文量', tone: 'accent' },
  { key: 'non_government_weibo_count', label: '非政府部门发文量', tone: 'obs' },
  { key: 'unclassified_weibo_count', label: '政府属性未标注', tone: 'obs' },
  { key: 'suspension_count', label: '停运记录', tone: 'attn' },
] as const
const dailyTrendIds = ['weibo_count', 'government_weibo_count', 'suspension_count']
const requestContext = computed(() =>
  ctx.dailyStats ? { dataset_id: ctx.datasetId, event_id: ctx.eventId } : ctx.params,
)

const summary = useLoader(
  (signal) => api.summary(ctx.dailyStats ? requestContext.value : { ...requestContext.value, hour_bj: ctx.cursor }, signal),
  () => [ctx.key, ctx.dailyStats ? null : ctx.cursor, ctx.dailyStats],
  { scope: () => ctx.scopeKey, enabled: () => ctx.ready },
)

const trend = useLoader(
  (signal) =>
    api.metrics(
      {
        ...requestContext.value,
        ...(ctx.dailyStats ? {} : { province_code: ctx.province || 'ALL' }),
        metric_id: ctx.dailyStats ? dailyTrendIds.join(',') : 'personal_weibo_count,official_weibo_count,affected_trains',
      },
      signal,
    ),
  () => [ctx.key, ctx.dailyStats],
  { scope: () => ctx.scopeKey, enabled: () => ctx.ready },
)

const mapMetric = ref<'physical_trains' | 'social_discussion' | 'org_official'>('physical_trains')
const mapOptions = [
  { key: 'physical_trains', label: '受影响车次' },
  { key: 'social_discussion', label: '个人微博' },
  { key: 'org_official', label: '官方发布' },
] as const

const s = computed(() => summary.data.value)
const cards = computed(() => s.value?.cards || {})
const phase = computed(() => (s.value?.phase ? PHASE_NAMES[s.value.phase] : null))
const eventRange = computed(() => {
  const { start, end } = s.value?.context || {}
  return start && end ? `${start.slice(0, 10)} 至 ${end.slice(0, 10)}` : ''
})

const metricItems = computed<MetricCardView[]>(() => {
  if (ctx.dailyStats) return dailyMetrics.map((metric) => ({ ...metric, card: cards.value[metric.key] }))
  const p = s.value?.phase
  return [
    { key: 'd', label: p === 'pre' ? '个人微博（关注度）' : '个人微博', card: cards.value.social_discussion, tone: 'obs' },
    { key: 'n', label: '负面情绪比例', card: cards.value.social_negative_ratio, tone: 'obs', digits: 2 },
    { key: 'o', label: p === 'pre' ? '官方发布（预警与准备）' : '官方发布', card: cards.value.org_official, tone: 'accent' },
    { key: 't', label: p === 'post' ? '受影响车次（复盘）' : '受影响车次', card: cards.value.physical_trains, tone: 'attn' },
    { key: 'h', label: '求助类微博', card: cards.value.help_requests, tone: 'obs' },
  ]
})

const mapCard = computed(() => cards.value[mapMetric.value])
const mapValues = computed(() => mapCard.value?.provinces || {})

const typhoon = computed(() => {
  const event = ctx.event
  if (event?.event_code !== 'SIM-DOKSURI-2023' && !['2305', '202305'].includes(event?.external_typhoon_id ?? '')) return undefined
  return !ctx.dailyStats && ctx.replayMode === 'as_known' ? DOKSURI_WARNINGS_ONLY : DOKSURI_OVERLAY
})

const unitLabel = computed(() => (ctx.province ? provinceName(ctx.province) : '全国（去重）'))
const personal = computed(() => seriesOf(trend.data.value?.items, 'personal_weibo_count'))
const official = computed(() => seriesOf(trend.data.value?.items, 'official_weibo_count'))
const trains = computed(() => seriesOf(trend.data.value?.items, 'affected_trains'))
const dailySeries = computed<ChartSeries[]>(() =>
  dailyTrendIds.map((id, index) => {
    const metric = dailyMetrics.find(({ key }) => key === id)!
    const points = seriesOf(trend.data.value?.items, id)
    const data: ChartSeries['data'] = []
    for (const [i, point] of points.entries()) {
      if (i > 0) {
        const nextDay = addHours(points[i - 1][0], 24)
        if (nextDay < point[0]) data.push([nextDay, null])
      }
      data.push(point)
    }
    return {
      name: metric.label,
      data,
      color: COLORS[metric.tone],
      type: index === 2 ? 'bar' : 'line',
      axis: index === 2 ? 1 : 0,
      symbol: true,
    }
  }),
)
const hourlySeries = computed<ChartSeries[]>(() => [
  { name: '个人微博（条）', data: personal.value, color: COLORS.obs, area: true },
  { name: '官方发布（条）', data: official.value, color: COLORS.accent, axis: 1 },
  { name: '受影响车次（列）', data: trains.value, color: COLORS.attn, type: 'bar', axis: 1 },
])
const trendSummary = computed(() =>
  ctx.dailyStats
    ? dailySeries.value.map((item) => `${item.name}有 ${item.data.filter(([, value]) => value != null).length} 天有观测`).join('，')
    : [describeSeries('个人微博', personal.value, '条'), describeSeries('官方发布', official.value, '条'), describeSeries('受影响车次', trains.value, '列')].join('；'),
)

function openAnomaly(id: number) {
  void router.push({ name: 'evidence', params: { id } })
}
</script>

<template>
  <div class="page overview">
    <div class="page-head overview-head">
      <div class="event-heading">
        <div class="event-title">
          <h1>事件总览</h1>
          <span v-if="typhoon" class="event-id">DOKSURI / 2305</span>
        </div>
        <p v-if="ctx.event?.name" class="event-name">{{ ctx.event.name }}</p>
      </div>
      <div v-if="ctx.dailyStats && eventRange" class="overview-context">
        <div class="metric-hour">
          <span class="muted small">统计时段（北京时间）</span>
          <strong class="num">{{ eventRange }}</strong>
        </div>
      </div>
      <div v-else-if="!ctx.dailyStats && s && !s.empty" class="overview-context">
        <span v-if="phase" class="tag info">{{ phase.label }}</span>
        <div class="metric-hour">
          <span class="muted small">指标时刻</span>
          <strong class="num">{{ fmtTime(s.card_hour) }}</strong>
        </div>
      </div>
    </div>

    <ContextGate>
      <StatusNote :status="summary.status.value" :error="summary.error.value" :stale="summary.stale.value" silent-refresh @retry="summary.reload" />
      <template v-if="s?.empty">
        <p class="note">{{ ctx.dailyStats ? '该事件的统计时段内还没有微博或停运记录。' : s.message }}</p>
        <RouterLink class="btn" to="/data">{{ ctx.dailyStats ? '前往数据管理导入' : '前往数据管理导入并运行分析' }}</RouterLink>
      </template>
      <template v-else-if="s">
        <p v-if="phase" class="muted small phase">{{ phase.hint }}</p>
        <p v-if="!ctx.dailyStats && ctx.strict" class="note info">当时已知模式：卡片、地图、列表与趋势只使用 {{ fmtTime(ctx.cursor) }} 之前已到达的数据；到达时间未知的记录不参与。</p>
        <div class="main-grid" :class="{ 'daily-without-map': ctx.dailyStats && !typhoon }">
          <section v-if="!ctx.dailyStats || typhoon" class="panel map-col" aria-labelledby="map-title">
            <div class="section-head">
              <div class="map-heading">
                <h2 id="map-title">{{ ctx.dailyStats ? '杜苏芮历史路径' : '省级分布' }}</h2>
                <p class="muted small">{{ ctx.dailyStats ? '路径与警戒线 · 全国统计见事件指标' : '点击省份筛选全站' }}</p>
              </div>
              <div v-if="!ctx.dailyStats" class="seg right" role="group" aria-label="地图指标">
                <button v-for="o in mapOptions" :key="o.key" type="button" :class="{ on: mapMetric === o.key }" :aria-pressed="mapMetric === o.key" @click="mapMetric = o.key">
                  {{ o.label }}
                </button>
              </div>
            </div>
            <div v-if="ctx.event && !ctx.dailyStats" ref="mobilePlayback" class="mobile-playback"></div>
            <ProvinceMap
              :values="ctx.dailyStats ? {} : mapValues"
              :selected="ctx.dailyStats ? null : ctx.province || null"
              :reference-only="ctx.dailyStats"
              :label="mapCard?.name || ''"
              :unit="mapCard?.unit"
              :typhoon="typhoon"
              :initial-basemap="typhoon && !ctx.dailyStats ? 'esa' : 'plain'"
              :metric-time="!ctx.dailyStats && typhoon?.track.length ? s.card_hour : undefined"
              :height="490"
              @select="(code) => (ctx.province = code || '')"
            />
            <TimeAxis
              v-if="ctx.event && !ctx.dailyStats"
              :key="ctx.event.id"
              :start="ctx.event.start_time"
              :end="ctx.event.end_time"
              :model-value="ctx.cursor"
              :playback-target="useCompactPlayback ? mobilePlayback : null"
              @update:model-value="ctx.setCursor"
            />
            <details v-if="typhoon || s.freshness?.length" class="map-notes">
              <summary class="muted small">地图来源与数据更新时间</summary>
              <p v-if="typhoon" class="map-caption muted small">
                <template v-if="typhoon.track.length">
                  杜苏芮（2305）历史路径为每 6 小时的中心位置。
                  <template v-if="!ctx.dailyStats">落在两次定位之间的指标时刻按时间比例插值。省级指标仍为当前数据集口径。</template>
                  <a :href="DOKSURI_TRACK_SOURCE" target="_blank" rel="noopener noreferrer">路径来源</a> ·
                </template>
                <template v-else>
                  「当时已知」只保留固定警戒线。历史路径是事后整理的，现有模拟预报也缺少可用于绘制走向的连续定位。
                </template>
                警戒线为固定监测参考。
                <a :href="WARNING_LINES_SOURCE" target="_blank" rel="noopener noreferrer">警戒线来源</a>
              </p>
              <ul v-if="s.freshness?.length" class="fresh small">
                <li v-for="f in s.freshness" :key="f.source">
                  <span class="muted">{{ f.source }}</span> 最新到达 <span class="num">{{ fmtTime(f.latest) }}</span>
                </li>
              </ul>
            </details>
          </section>

          <aside class="overview-rail" aria-label="指标与核查">
            <section class="panel metrics-col" aria-labelledby="metrics-title">
              <h2 id="metrics-title">{{ ctx.dailyStats ? '事件指标 · 时段累计' : '事件指标' }}</h2>
              <MetricCards :items="metricItems" :daily="ctx.dailyStats" />
            </section>
            <section v-if="!ctx.dailyStats" class="panel review-col" aria-labelledby="review-title">
              <div class="section-head">
                <h2 id="review-title">待核查动态</h2>
                <RouterLink class="right small" to="/evidence">全部 ›</RouterLink>
              </div>
              <div class="counts-grid" aria-label="异常数量统计">
                <div class="count-cell">
                  <span class="muted small">单维</span>
                  <strong class="num c-accent">{{ s.anomaly_counts?.single ?? 0 }}</strong>
                </div>
                <div class="count-cell">
                  <span class="muted small">两维</span>
                  <strong class="num c-attn">{{ s.anomaly_counts?.pair ?? 0 }}</strong>
                </div>
                <div class="count-cell">
                  <span class="muted small">三维</span>
                  <strong class="num c-danger">{{ s.anomaly_counts?.joint ?? 0 }}</strong>
                </div>
              </div>
              <p v-if="s.pending_window" class="muted small counts">窗口未成熟 {{ s.pending_window }} 条（待确认）</p>
              <AnomalyPanel :items="(s.to_review || []).slice(0, 5)" empty-text="当前条件下没有未核验的异常。" @open="openAnomaly" />
              <RouterLink class="impact-link" to="/overview/impact">影响事件与行动 ›</RouterLink>
            </section>
          </aside>

          <section class="panel trend-col" aria-labelledby="trend-title">
            <div class="section-head">
              <h2 id="trend-title">{{ ctx.dailyStats ? '每日微博与停运趋势' : '三维影响趋势' }}</h2>
              <span v-if="ctx.dailyStats" class="muted small">全国 · 按日统计</span>
              <span v-else class="muted small">{{ unitLabel }} · 小时粒度 · 点击图表移动分析时刻</span>
            </div>
            <StatusNote :status="trend.status.value" :error="trend.error.value" :stale="trend.stale.value" silent-refresh @retry="trend.reload" />
            <TrendChart
              :series="ctx.dailyStats ? dailySeries : hourlySeries"
              :daily="ctx.dailyStats"
              :axes="ctx.dailyStats ? [{ name: '微博（条）', min: 0 }, { name: '停运（车次日）', min: 0, right: true }] : [{ name: '微博量' }, { name: '发布/车次', right: true }]"
              :cursor="ctx.dailyStats ? null : ctx.cursor"
              :cursor-label="ctx.dailyStats ? '' : fmtTime(ctx.cursor)"
              :x-min="ctx.dailyStats ? undefined : ctx.event?.start_time"
              :x-max="ctx.dailyStats ? undefined : ctx.event?.end_time"
              :height="260"
              :summary="trendSummary"
              :aria-label="ctx.dailyStats ? '每日微博与停运趋势' : '三维影响趋势'"
              @pick="(time) => { if (!ctx.dailyStats) ctx.setCursor(time) }"
            />
          </section>
        </div>
      </template>
    </ContextGate>
  </div>
</template>

<style scoped>
.overview-head {
  align-items: flex-end;
  justify-content: space-between;
  gap: 14px 20px;
  padding: 0 0 13px;
}
.event-title {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 4px 14px;
}
.event-id {
  padding: 2px 8px;
  border-radius: 6px;
  border: 1px solid color-mix(in oklab, var(--accent) 30%, transparent);
  background: var(--accent-soft);
  color: var(--accent-hover);
  font-family: var(--font-mono);
  font-size: 11.5px;
  font-weight: 550;
  letter-spacing: 0.06em;
}
.event-name {
  margin: 4px 0 0;
  color: var(--muted);
  font-size: 14px;
}
.overview-context {
  display: flex;
  align-items: center;
  gap: 12px;
}
.metric-hour {
  display: grid;
  gap: 1px;
  padding: 6px 12px;
  border: 1px solid var(--line);
  border-radius: var(--control-radius);
  background: var(--surface);
}
.metric-hour strong {
  font-family: var(--font-mono);
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
}
.phase {
  margin: -8px 0 12px;
}
.map-caption {
  margin: 8px 0 0;
}
.mobile-playback {
  display: none;
}
.map-notes {
  margin-top: 10px;
}
.map-notes summary {
  width: fit-content;
  cursor: pointer;
}
.main-grid {
  display: grid;
  grid-template-areas: 'map rail' 'trend rail';
  grid-template-columns: minmax(0, 1fr) minmax(272px, 30%);
  align-items: start;
  gap: 16px;
  margin-top: 16px;
}
.map-col {
  grid-area: map;
}
.daily-without-map {
  grid-template-areas: 'trend rail';
}
.overview-rail {
  grid-area: rail;
  display: grid;
  gap: 16px;
  min-width: 0;
}
.metrics-col h2 {
  margin-bottom: 10px;
}
.trend-col {
  grid-area: trend;
}
.map-col .section-head {
  align-items: center;
}
.map-heading p {
  margin: 2px 0 0;
}
.map-col .seg button {
  padding-inline: 10px;
  font-size: 12px;
}
.review-col .section-head {
  margin-bottom: 8px;
}
.counts-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
  margin: 0 0 10px;
}
.count-cell {
  display: grid;
  justify-items: center;
  gap: 2px;
  padding: 7px 6px;
  border: 1px solid var(--line);
  border-radius: var(--control-radius);
  background: color-mix(in oklab, var(--surface-tint) 65%, var(--surface));
}
.count-cell strong {
  font-family: var(--font-mono);
  font-size: 16px;
  line-height: 1.15;
}
.c-accent { color: var(--accent); }
.c-attn { color: var(--attn); }
.c-danger { color: var(--danger); }
.counts {
  margin: 0 0 8px;
}
.fresh {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  list-style: none;
  padding: 8px 0 0;
  margin: 10px 0 0;
  border-top: 1px solid var(--line);
}
.impact-link {
  display: inline-block;
  margin-top: 12px;
}
@media (max-width: 900px) {
  .main-grid {
    grid-template-areas: 'map' 'rail' 'trend';
    grid-template-columns: 1fr;
  }
  .daily-without-map {
    grid-template-areas: 'rail' 'trend';
  }
}
@media (max-width: 760px) {
  .mobile-playback {
    display: block;
    margin-bottom: 8px;
  }
  .map-col .section-head .right {
    margin-left: 0;
  }
}
@media (max-width: 360px) {
  .map-col .seg button {
    padding-inline: 8px;
  }
}
</style>
