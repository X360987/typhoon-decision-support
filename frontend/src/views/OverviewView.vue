<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import AnomalyPanel from '../components/AnomalyPanel.vue'
import ContextGate from '../components/ContextGate.vue'
import MetricCards, { type MetricCardView } from '../components/MetricCards.vue'
import ProvinceMap, { type TrackPoint } from '../components/ProvinceMap.vue'
import StatusNote from '../components/StatusNote.vue'
import TrendChart from '../components/TrendChart.vue'
import { useLoader } from '../composables/useLoader'
import { PHASE_NAMES, fmtTime, provinceName } from '../lib/format'
import { COLORS, describeSeries, seriesOf } from '../lib/series'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const router = useRouter()

const summary = useLoader(
  (signal) => api.summary({ ...ctx.params, hour_bj: ctx.cursor }, signal),
  () => [ctx.key, ctx.cursor],
  { scope: () => ctx.scopeKey, enabled: () => ctx.ready },
)

const trend = useLoader(
  (signal) =>
    api.metrics(
      {
        ...ctx.params,
        province_code: ctx.province || 'ALL',
        metric_id: 'personal_weibo_count,official_weibo_count,affected_trains',
      },
      signal,
    ),
  () => ctx.key,
  { scope: () => ctx.scopeKey, enabled: () => ctx.ready },
)

const forecasts = useLoader(
  (signal) => api.forecasts({ dataset_id: ctx.datasetId, event_id: ctx.eventId, replay_mode: ctx.replayMode, as_of: ctx.strict ? ctx.cursor : undefined }, signal),
  () => ctx.key,
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

const metricItems = computed<MetricCardView[]>(() => {
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

const track = computed<TrackPoint[]>(() =>
  (forecasts.data.value?.latest_points || [])
    .filter((p) => p.lat != null && p.lon != null)
    .map((p) => ({ lat: p.lat as number, lon: p.lon as number, label: `+${p.lead_hours}h ${fmtTime(p.valid_time)} ${p.metric} ${p.value ?? ''}${p.unit ?? ''}` })),
)

const unitLabel = computed(() => (ctx.province ? provinceName(ctx.province) : '全国（去重）'))
const personal = computed(() => seriesOf(trend.data.value?.items, 'personal_weibo_count'))
const official = computed(() => seriesOf(trend.data.value?.items, 'official_weibo_count'))
const trains = computed(() => seriesOf(trend.data.value?.items, 'affected_trains'))
const trendSummary = computed(() =>
  [describeSeries('个人微博', personal.value, '条'), describeSeries('官方发布', official.value, '条'), describeSeries('受影响车次', trains.value, '列')].join('；'),
)

function openAnomaly(id: number) {
  void router.push({ name: 'evidence', params: { id } })
}
</script>

<template>
  <div class="page overview">
    <div class="page-head">
      <h1>事件总览</h1>
      <span class="muted">{{ ctx.event?.name }}</span>
      <span v-if="s && !s.empty" class="muted num">指标时刻 {{ fmtTime(s.card_hour) }}</span>
      <span v-if="phase" class="tag info">{{ phase.label }}</span>
      <span class="tag" :class="ctx.dataMode === 'real' ? 'real' : 'demo'">{{ s?.banner || (ctx.dataMode === 'real' ? '真实数据' : '模拟数据') }}</span>
    </div>

    <ContextGate>
      <StatusNote :status="summary.status.value" :error="summary.error.value" :stale="summary.stale.value" @retry="summary.reload" />
      <template v-if="s?.empty">
        <p class="note">{{ s.message }}</p>
        <RouterLink class="btn" to="/data">前往数据管理导入并运行分析</RouterLink>
      </template>
      <template v-else-if="s">
        <p v-if="phase" class="muted small phase">{{ phase.hint }}</p>
        <p v-if="ctx.strict" class="note info">当时已知模式：卡片、地图、列表与趋势只使用 {{ fmtTime(ctx.cursor) }} 之前已到达的数据；到达时间未知的记录不参与。</p>
        <MetricCards :items="metricItems" />

        <div class="main-grid">
          <section class="map-col" aria-labelledby="map-title">
            <div class="section-head">
              <h2 id="map-title">省级分布</h2>
              <span class="muted small">{{ fmtTime(mapCard?.hour_bj) }} · 点击省份筛选全站</span>
              <div class="seg right" role="group" aria-label="地图指标">
                <button v-for="o in mapOptions" :key="o.key" type="button" :class="{ on: mapMetric === o.key }" @click="mapMetric = o.key">
                  {{ o.label }}
                </button>
              </div>
            </div>
            <ProvinceMap
              :values="mapValues"
              :selected="ctx.province || null"
              :label="mapCard?.name || ''"
              :unit="mapCard?.unit"
              :track="track"
              track-label="预报路径（最新快照，模拟）"
              :height="440"
              @select="(code) => (ctx.province = code || '')"
            />
            <ul class="fresh small">
              <li v-for="f in s.freshness" :key="f.source">
                <span class="muted">{{ f.source }}</span> 最新到达 <span class="num">{{ fmtTime(f.latest) }}</span>
              </li>
            </ul>
          </section>

          <aside class="review-col" aria-labelledby="review-title">
            <div class="section-head">
              <h2 id="review-title">待核查动态</h2>
              <RouterLink class="right small" to="/evidence">全部 ›</RouterLink>
            </div>
            <p class="muted small counts">
              单维 {{ s.anomaly_counts?.single ?? 0 }} · 两维 {{ s.anomaly_counts?.pair ?? 0 }} · 三维 {{ s.anomaly_counts?.joint ?? 0 }}
              <template v-if="s.pending_window">· 窗口未成熟 {{ s.pending_window }} 条（待确认）</template>
            </p>
            <AnomalyPanel :items="(s.to_review || []).slice(0, 5)" empty-text="当前条件下没有未核验的异常。" @open="openAnomaly" />
            <RouterLink class="impact-link" to="/overview/impact">影响事件与行动 ›</RouterLink>
          </aside>
        </div>

        <section class="section" aria-labelledby="trend-title">
          <div class="section-head">
            <h2 id="trend-title">三维影响趋势</h2>
            <span class="muted small">{{ unitLabel }} · 小时粒度 · 点击图表移动分析时刻</span>
          </div>
          <StatusNote :status="trend.status.value" :error="trend.error.value" :stale="trend.stale.value" @retry="trend.reload" />
          <TrendChart
            :series="[
              { name: '个人微博（条）', data: personal, color: COLORS.obs, area: true },
              { name: '官方发布（条）', data: official, color: COLORS.accent, axis: 1 },
              { name: '受影响车次（列）', data: trains, color: COLORS.attn, type: 'bar', axis: 1 },
            ]"
            :axes="[{ name: '微博量' }, { name: '发布/车次', right: true }]"
            :cursor="ctx.cursor"
            :cursor-label="fmtTime(ctx.cursor)"
            :x-min="ctx.event?.start_time"
            :x-max="ctx.event?.end_time"
            :height="260"
            :summary="trendSummary"
            aria-label="三维影响趋势"
            @pick="ctx.setCursor"
          />
        </section>
      </template>
    </ContextGate>
  </div>
</template>

<style scoped>
.phase {
  margin: -8px 0 10px;
}
.main-grid {
  display: grid;
  grid-template-columns: minmax(0, 68fr) minmax(260px, 32fr);
  gap: 28px;
  margin-top: 20px;
}
.review-col {
  border-left: 1px solid var(--line);
  padding-left: 22px;
}
.counts {
  margin: -4px 0 4px;
}
.fresh {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  list-style: none;
  padding: 0;
  margin: 8px 0 0;
}
.impact-link {
  display: inline-block;
  margin-top: 12px;
}
@media (max-width: 1100px) {
  .main-grid {
    grid-template-columns: 1fr;
  }
  .review-col {
    border-left: 0;
    padding-left: 0;
    border-top: 1px solid var(--line);
    padding-top: 14px;
  }
}
</style>
