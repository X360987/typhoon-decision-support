<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import type { MetricPoint } from '../api/types'
import ContextGate from '../components/ContextGate.vue'
import StatusNote from '../components/StatusNote.vue'
import TrendChart, { type ChartSeries } from '../components/TrendChart.vue'
import { useLoader } from '../composables/useLoader'
import { dimensionNames, REVIEW_NAMES, SCOPE_NAMES, addHours, anomalyName, fmtNum, fmtTime, provinceName } from '../lib/format'
import { COLORS, describeSeries, rollingMean, seriesOf, valueAt, type SeriesData } from '../lib/series'
import { useContextStore } from '../stores/context'

type Tab = 'social' | 'org' | 'physical' | 'coupling'

const ctx = useContextStore()
const route = useRoute()
const router = useRouter()
const tab = computed<Tab>(() => (route.params.tab as Tab) || 'social')
const tabs: Array<{ id: Tab; label: string; title: string }> = [
  { id: 'social', label: '社会', title: '社会影响分析' },
  { id: 'org', label: '组织', title: '组织发布分析' },
  { id: 'physical', label: '物理', title: '交通影响分析' },
  { id: 'coupling', label: '耦合', title: '维度耦合分析' },
]
const current = computed(() => tabs.find((t) => t.id === tab.value) || tabs[0])
const opts = { scope: () => ctx.scopeKey, enabled: () => ctx.ready }
const unit = computed(() => ctx.province || 'ALL')

const METRICS = 'negative_ratio,personal_weibo_count,help_request_count,official_weibo_count,affected_trains,affected_stations,suspension_events'
const series = useLoader((signal) => api.metrics({ ...ctx.params, province_code: unit.value, metric_id: METRICS }, signal), () => ctx.key, opts)
const registry = useLoader((signal) => api.registry(signal), () => ctx.ready, { enabled: () => ctx.ready })
const needsCoverage = computed(() => tab.value === 'org' || tab.value === 'coupling')
const coverage = useLoader(
  (signal) => api.coverage({ dataset_id: ctx.datasetId, event_id: ctx.eventId, data_version: ctx.dataVersion || undefined }, signal),
  () => [ctx.scopeKey, ctx.revision, needsCoverage.value],
  { enabled: () => ctx.ready && needsCoverage.value },
)
const impact = useLoader((signal) => api.impact(ctx.params, signal), () => [ctx.key, tab.value], {
  ...opts,
  enabled: () => ctx.ready && tab.value === 'physical',
})
const topicWindow = computed(() => {
  const end = ctx.cursor || ctx.event?.end_time || ''
  return { end, mid: addHours(end, -24), start: addHours(end, -48) }
})
const topicsNow = useLoader(
  (signal) => api.topics({ ...ctx.params, start: topicWindow.value.mid, end: topicWindow.value.end }, signal),
  () => [ctx.key, ctx.cursor, tab.value],
  { ...opts, enabled: () => ctx.ready && tab.value === 'social' },
)
const topicsPrev = useLoader(
  (signal) => api.topics({ ...ctx.params, start: topicWindow.value.start, end: topicWindow.value.mid }, signal),
  () => [ctx.key, ctx.cursor, tab.value],
  { ...opts, enabled: () => ctx.ready && tab.value === 'social' },
)
const listFilter = computed(() => {
  if (tab.value === 'coupling') return { analysis_scope: 'pair,joint', dimension: undefined }
  const dim = { social: 'social', org: 'organizational', physical: 'physical' }[tab.value]
  return { analysis_scope: 'single', dimension: dim }
})
const anomalies = useLoader(
  (signal) => api.anomalies({ ...ctx.params, ...listFilter.value, page_size: 12 }, signal),
  () => [ctx.key, tab.value],
  opts,
)

const items = computed<MetricPoint[] | undefined>(() => series.data.value?.items)
const rules = computed(() => registry.data.value?.rules || {})
const single = computed(() => (rules.value.single || {}) as Record<string, unknown>)
const windowHours = computed(() => Number(single.value.window_hours ?? 12))
const minSamples = computed(() => Number(single.value.min_samples ?? 6))
const negFloor = computed(() => Number(((single.value.social || {}) as Record<string, unknown>).negative_ratio_abs_floor ?? 0.35))

const neg = computed(() => seriesOf(items.value, 'negative_ratio'))
const negBase = computed(() => rollingMean(neg.value, windowHours.value))
const personal = computed(() => seriesOf(items.value, 'personal_weibo_count'))
const official = computed(() => seriesOf(items.value, 'official_weibo_count'))
const officialBase = computed(() => rollingMean(official.value, windowHours.value))
const trains = computed(() => seriesOf(items.value, 'affected_trains'))
const stations = computed(() => seriesOf(items.value, 'affected_stations'))
const suspensions = computed(() => seriesOf(items.value, 'suspension_events'))

function constant(data: SeriesData, value: number): SeriesData {
  return data.map(([t]) => [t, value])
}
function normalized(data: SeriesData): SeriesData {
  const max = Math.max(0, ...data.map(([, v]) => v ?? 0))
  return data.map(([t, v]) => [t, v == null || max === 0 ? null : Number((v / max).toFixed(3))])
}

const chart = computed<{ series: ChartSeries[]; summary: string; axis: string }>(() => {
  if (tab.value === 'social')
    return {
      axis: '比例',
      series: [
        { name: '负面情绪比例（观测）', data: neg.value, color: COLORS.obs },
        { name: `${windowHours.value} 小时滚动基线`, data: negBase.value, color: COLORS.muted, dashed: true },
        { name: `绝对阈值（${negFloor.value}）`, data: constant(neg.value, negFloor.value), color: COLORS.attn, dashed: true },
      ],
      summary: describeSeries('负面情绪比例', neg.value),
    }
  if (tab.value === 'org')
    return {
      axis: '条',
      series: [
        { name: '官方发布（观测）', data: official.value, color: COLORS.accent, type: 'bar' },
        { name: `${windowHours.value} 小时滚动基线`, data: officialBase.value, color: COLORS.muted, dashed: true },
      ],
      summary: describeSeries('官方发布', official.value, '条') + '。缺测小时留空，不按零发布处理。',
    }
  if (tab.value === 'physical')
    return {
      axis: '数量',
      series: [
        { name: '受影响车次（运行实例去重）', data: trains.value, color: COLORS.attn, type: 'bar' },
        { name: '受影响站点（站点集合）', data: stations.value, color: COLORS.violet },
        { name: '停运公告数', data: suspensions.value, color: COLORS.muted, dashed: true },
      ],
      summary: describeSeries('受影响车次', trains.value, '列'),
    }
  return {
    axis: '相对峰值',
    series: [
      { name: '社会·个人微博', data: normalized(personal.value), color: COLORS.obs },
      { name: '组织·官方发布', data: normalized(official.value), color: COLORS.accent },
      { name: '物理·受影响车次', data: normalized(trains.value), color: COLORS.attn },
    ],
    summary: '三条曲线各自除以本序列峰值后对齐，仅用于比较起伏时序，不表示数量关系或因果。',
  }
})

const at = computed(() => {
  const point = (items.value || []).find(
    (p) => p.metric_id === (tab.value === 'org' ? 'official_weibo_count' : tab.value === 'physical' ? 'affected_trains' : 'negative_ratio') && p.hour_bj.slice(0, 13) === (ctx.cursor || '').slice(0, 13),
  )
  return point || null
})
const baseAt = computed(() => valueAt(tab.value === 'org' ? officialBase.value : negBase.value, ctx.cursor))
const sampleOk = computed(() => (at.value?.sample_size ?? 0) >= minSamples.value)

const topicRows = computed(() => {
  const prev = new Map((topicsPrev.data.value?.items || []).map((i) => [i.keyword, i.count]))
  const rows = (topicsNow.data.value?.items || []).map((i) => ({ keyword: i.keyword, now: i.count, prev: prev.get(i.keyword) ?? 0 }))
  for (const [k, v] of prev) if (!rows.some((r) => r.keyword === k)) rows.push({ keyword: k, now: 0, prev: v })
  return rows.sort((a, b) => b.now - a.now).slice(0, 6)
})
const topicMax = computed(() => Math.max(1, ...topicRows.value.flatMap((r) => [r.now, r.prev])))

const orgRows = computed(() => {
  const matrix = coverage.data.value?.metric_matrix || {}
  const covered = new Set(coverage.data.value?.org_covered_provinces || [])
  return Object.keys(matrix)
    .filter((p) => p !== 'ALL')
    .sort()
    .map((p) => ({
      province: p,
      covered: covered.has(p),
      hours: matrix[p]?.official_weibo_count?.hours ?? 0,
      posts: matrix[p]?.official_weibo_count?.samples ?? 0,
      socialHours: matrix[p]?.personal_weibo_count?.hours ?? 0,
    }))
})

const TASKS: Array<{ id: string; label: string }> = [
  { id: 'pair_social_org', label: '社会 × 组织' },
  { id: 'pair_social_physical', label: '社会 × 物理' },
  { id: 'pair_org_physical', label: '组织 × 物理（滞后）' },
  { id: 'joint', label: '三维联合' },
]
const taskProvinces = computed(() => {
  const tasks = coverage.data.value?.tasks || {}
  return Array.from(new Set(Object.values(tasks).flatMap((row) => Object.keys(row)))).sort()
})
function cell(task: string, prov: string) {
  const v = coverage.data.value?.tasks?.[task]?.[prov]
  if (!v) return { text: '未运行', cls: '' }
  if (v === 'anomaly') return { text: '异常', cls: 'bad' }
  if (v === 'normal') return { text: '正常', cls: 'ok' }
  return { text: `证据不足（${v.replace('insufficient:', '')}）`, cls: 'attn' }
}

const impactCounts = computed(() => {
  const c = { mapped: 0, pending_review: 0, unmapped: 0 }
  for (const s of impact.data.value?.suspensions || []) c[s.mapping_status] += 1
  return c
})

function openAnomaly(id: number) {
  void router.push({ name: 'evidence', params: { id } })
}
function onRowKey(e: KeyboardEvent, id: number) {
  if (e.key === 'Enter') openAnomaly(id)
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>{{ current.title }}</h1>
      <span class="muted">{{ provinceName(unit) }} · 规则版本 {{ registry.data.value?.rule_version || '—' }}</span>
    </div>
    <nav class="tabs" aria-label="分析维度">
      <RouterLink v-for="t in tabs" :key="t.id" :to="`/analysis/${t.id}`" :class="{ on: tab === t.id }">{{ t.label }}</RouterLink>
    </nav>
    <ContextGate>
      <div class="analysis-grid">
        <section aria-label="指标曲线">
          <StatusNote :status="series.status.value" :error="series.error.value" :stale="series.stale.value" @retry="series.reload" />
          <TrendChart
            :series="chart.series"
            :axes="[{ name: chart.axis }]"
            :cursor="ctx.cursor"
            :cursor-label="fmtTime(ctx.cursor)"
            :x-min="ctx.event?.start_time"
            :x-max="ctx.event?.end_time"
            :height="320"
            :summary="chart.summary"
            :aria-label="current.title"
            @pick="ctx.setCursor"
          />
        </section>

        <aside class="basis" aria-labelledby="basis-title">
          <h2 id="basis-title">判定依据</h2>
          <template v-if="tab === 'social' || tab === 'org' || tab === 'physical'">
            <dl>
              <dt>观测值</dt>
              <dd>
                <span class="big num" :class="tab === 'physical' ? 'attn' : 'obs'">{{ fmtNum(at?.value, tab === 'social' ? 2 : 0) }}</span>
                <span class="muted small">（{{ fmtTime(ctx.cursor) }}）</span>
                <div v-if="!at" class="muted small">该小时缺测或尚未到达，不按 0 处理。</div>
              </dd>
              <template v-if="tab !== 'physical'">
                <dt>基线</dt>
                <dd>
                  <span class="mid num">{{ fmtNum(baseAt, tab === 'social' ? 2 : 1) }}</span>
                  <div class="muted small">前 {{ windowHours }} 小时真实时间窗内有观测小时的均值</div>
                </dd>
              </template>
              <dt>样本量</dt>
              <dd>
                <span class="mid num">{{ at?.sample_size ?? '—' }}</span>
                <div class="muted small">最小样本 {{ minSamples }}（来自规则配置）</div>
              </dd>
              <dt>证据状态</dt>
              <dd>
                <span v-if="!at" class="tag">无观测</span>
                <span v-else-if="tab === 'social' && !sampleOk" class="tag attn">样本不足，不判定</span>
                <span v-else class="tag ok">可判定</span>
              </dd>
              <template v-if="tab === 'social'">
                <dt>阈值</dt>
                <dd class="small">绝对下限 {{ negFloor }}；稳健 z ≥ {{ single.mad_z_threshold ?? 3 }} 或分位数 {{ single.quantile_threshold ?? 0.95 }}</dd>
              </template>
              <template v-if="tab === 'physical'">
                <dt>映射状态</dt>
                <dd class="small">
                  已映射 {{ impactCounts.mapped }} · 待核验 {{ impactCounts.pending_review }} · 未映射 {{ impactCounts.unmapped }}
                  <div class="muted">{{ impact.data.value?.recovery.message }}</div>
                </dd>
              </template>
            </dl>
          </template>
          <template v-else>
            <p class="small">两维关系只在两个维度都有覆盖的省份运行；三维联合要求三维均可用，按维度计数。组织缺测的省份不输出任何组织关系结论。</p>
            <p class="small muted">相关与同步只说明时序上的共同变化，不作因果或责任结论。</p>
          </template>
          <RouterLink class="small" :to="{ name: 'evidence' }">查看原始证据 →</RouterLink>
        </aside>
      </div>

      <div class="lower-grid">
        <section v-if="tab === 'social'" aria-labelledby="topic-title">
          <div class="section-head">
            <h2 id="topic-title">话题频次</h2>
            <span class="muted small">{{ topicsNow.data.value?.method }} · 样本 {{ topicsNow.data.value?.sample_size ?? 0 }} 条</span>
          </div>
          <p class="legend small"><span class="sw now"></span>近 24 小时 <span class="sw prev"></span>前 24 小时</p>
          <StatusNote :status="topicsNow.status.value" :error="topicsNow.error.value" :empty="!topicRows.length" empty-text="此时段没有命中关键词的个人微博。" @retry="topicsNow.reload" />
          <ul class="bars">
            <li v-for="r in topicRows" :key="r.keyword">
              <span class="kw">{{ r.keyword }}</span>
              <span class="bar-pair">
                <span class="bar now" :style="{ width: `${(r.now / topicMax) * 100}%` }"></span>
                <span class="bar prev" :style="{ width: `${(r.prev / topicMax) * 100}%` }"></span>
              </span>
              <span class="num nums"><strong>{{ r.now }}</strong><span class="muted">{{ r.prev }}</span></span>
            </li>
          </ul>
        </section>

        <section v-else-if="tab === 'org'" aria-labelledby="cov-title">
          <div class="section-head"><h2 id="cov-title">地区覆盖</h2></div>
          <StatusNote :status="coverage.status.value" :error="coverage.error.value" @retry="coverage.reload" />
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>省份</th>
                  <th>组织覆盖</th>
                  <th>官方发布有观测小时</th>
                  <th>官方微博数</th>
                  <th>社会有观测小时</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in orgRows" :key="r.province">
                  <td>{{ provinceName(r.province) }}</td>
                  <td><span class="tag" :class="r.covered ? 'ok' : 'attn'">{{ r.covered ? '已覆盖' : '缺测（不判定组织关系）' }}</span></td>
                  <td class="num">{{ r.hours }}</td>
                  <td class="num">{{ r.posts }}</td>
                  <td class="num">{{ r.socialHours }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-else-if="tab === 'physical'" aria-labelledby="seg-title">
          <div class="section-head">
            <h2 id="seg-title">停运区段</h2>
            <RouterLink class="right small" to="/overview/impact">完整影响事件 ›</RouterLink>
          </div>
          <StatusNote :status="impact.status.value" :error="impact.error.value" :empty="!impact.data.value?.suspensions.length" empty-text="无停运记录。" @retry="impact.reload" />
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>车次</th>
                  <th>区段</th>
                  <th>站点</th>
                  <th>映射</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="s in impact.data.value?.suspensions.slice(0, 10) || []" :key="s.id">
                  <td>{{ s.train_code }}</td>
                  <td>{{ s.segment[0] || s.segment[1] ? `${s.segment[0] || '?'} → ${s.segment[1] || '?'}` : s.scope || '全程' }}</td>
                  <td class="num">{{ s.stations.length || '—' }}</td>
                  <td>{{ s.mapping_status === 'mapped' ? '已映射' : s.mapping_status === 'pending_review' ? '待核验' : '未映射' }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section v-else aria-labelledby="matrix-title">
          <div class="section-head"><h2 id="matrix-title">关系任务状态</h2><span class="muted small">每个省份、每项任务独立判定</span></div>
          <StatusNote :status="coverage.status.value" :error="coverage.error.value" @retry="coverage.reload" />
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>任务</th>
                  <th v-for="p in taskProvinces" :key="p">{{ provinceName(p) }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="t in TASKS" :key="t.id">
                  <td>{{ t.label }}</td>
                  <td v-for="p in taskProvinces" :key="p"><span class="tag" :class="cell(t.id, p).cls">{{ cell(t.id, p).text }}</span></td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>

        <section aria-labelledby="obs-title">
          <div class="section-head">
            <h2 id="obs-title">{{ tab === 'coupling' ? '关系与联合异常' : '异常观测' }}</h2>
            <span class="muted small">共 {{ anomalies.data.value?.total ?? 0 }} 条</span>
          </div>
          <StatusNote :status="anomalies.status.value" :error="anomalies.error.value" :empty="!anomalies.data.value?.items.length" empty-text="当前条件下没有异常。" @retry="anomalies.reload" />
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>地区</th>
                  <th>类型</th>
                  <th>维度</th>
                  <th>核验</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="a in anomalies.data.value?.items || []"
                  :key="a.id"
                  class="clickable"
                  tabindex="0"
                  @click="openAnomaly(a.id)"
                  @keydown="onRowKey($event, a.id)"
                >
                  <td class="num">{{ fmtTime(a.hour_bj) }}</td>
                  <td>{{ provinceName(a.province_code) }}</td>
                  <td>{{ anomalyName(a.anomaly_type) }}<span v-if="a.requires_future_window" class="tag attn">滞后窗口</span></td>
                  <td>{{ SCOPE_NAMES[a.analysis_scope] }} · {{ dimensionNames(a.dimensions, '/') }}</td>
                  <td>{{ REVIEW_NAMES[a.review_status] || a.review_status }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      </div>
    </ContextGate>
  </div>
</template>

<style scoped>
.tabs {
  margin-bottom: 18px;
}
.analysis-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 28px;
}
.basis {
  border-left: 1px solid var(--line);
  padding-left: 22px;
}
.basis dl {
  margin: 10px 0;
}
.basis dt {
  color: var(--muted);
  font-size: 13px;
  margin-top: 12px;
}
.basis dd {
  margin: 2px 0 0;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--line);
}
.big {
  font-size: 30px;
  font-weight: 700;
}
.big.obs {
  color: var(--obs);
}
.big.attn {
  color: var(--attn);
}
.mid {
  font-size: 20px;
  font-weight: 650;
}
.lower-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 32px;
  margin-top: 26px;
}
.legend {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--muted);
  margin: 0 0 8px;
}
.sw {
  display: inline-block;
  width: 14px;
  height: 8px;
  border-radius: 2px;
}
.sw.now,
.bar.now {
  background: var(--obs);
}
.sw.prev,
.bar.prev {
  background: #cfd8e3;
}
.bars {
  list-style: none;
  padding: 0;
  margin: 0;
}
.bars li {
  display: grid;
  grid-template-columns: 56px 1fr 64px;
  gap: 10px;
  align-items: center;
  padding: 8px 0;
}
.bar-pair {
  display: grid;
  gap: 4px;
}
.bar {
  display: block;
  height: 9px;
  border-radius: 2px;
  min-width: 2px;
}
.nums {
  display: grid;
  text-align: right;
}
@media (max-width: 1100px) {
  .analysis-grid,
  .lower-grid {
    grid-template-columns: 1fr;
  }
  .basis {
    border-left: 0;
    padding-left: 0;
  }
}
</style>
