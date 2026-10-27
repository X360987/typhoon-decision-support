<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../api/client'
import type { PredictionItem } from '../api/types'
import ContextGate from '../components/ContextGate.vue'
import StatusNote from '../components/StatusNote.vue'
import TrendChart from '../components/TrendChart.vue'
import { useLoader } from '../composables/useLoader'
import { addHours, errorText, fmtNum, fmtTime, hourFloor, provinceName } from '../lib/format'
import { COLORS, describeSeries, seriesOf, type SeriesData } from '../lib/series'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const target = ref('affected_trains')
const origin = ref('')
const customOrigin = ref('')
const lead = ref(3)
const runState = ref<{ status: 'idle' | 'running' | 'done' | 'failed'; text: string }>({ status: 'idle', text: '' })

const unit = computed(() => ctx.province || 'ALL')
const opts = { scope: () => ctx.scopeKey, enabled: () => ctx.ready }

watch(
  () => ctx.scopeKey,
  () => {
    origin.value = ''
    runState.value = { status: 'idle', text: '' }
  },
)

const preds = useLoader(
  (signal) =>
    api.predictions(
      { dataset_id: ctx.datasetId, event_id: ctx.eventId, origin_time: origin.value || undefined, target_id: target.value, province_code: unit.value },
      signal,
    ),
  () => [ctx.scopeKey, ctx.revision, origin.value, target.value, unit.value],
  opts,
)

const run = computed(() => preds.data.value?.run || null)
const originTime = computed(() => run.value?.origin_time || origin.value || '')

const history = useLoader(
  (signal) =>
    api.metrics(
      {
        dataset_id: ctx.datasetId,
        event_id: ctx.eventId,
        province_code: unit.value,
        metric_id: target.value,
        replay_mode: 'as_known',
        as_of: originTime.value,
        data_version: ctx.dataVersion || undefined,
      },
      signal,
    ),
  () => [ctx.scopeKey, originTime.value, target.value, unit.value],
  { ...opts, enabled: () => ctx.ready && !!originTime.value },
)
const actual = useLoader(
  (signal) =>
    api.metrics(
      { dataset_id: ctx.datasetId, event_id: ctx.eventId, province_code: unit.value, metric_id: target.value, replay_mode: 'retrospective' },
      signal,
    ),
  () => [ctx.scopeKey, target.value, unit.value, ctx.replayMode],
  { ...opts, enabled: () => ctx.ready && ctx.replayMode === 'retrospective' },
)

const targets = computed(() => preds.data.value?.targets || [])
const targetMeta = computed(() => targets.value.find((t) => t.id === target.value))
const horizons = computed(() => preds.data.value?.horizons || [1, 3, 6, 12, 24])
const mlHorizon = computed(() => preds.data.value?.ml_horizon ?? 3)
const rows = computed<PredictionItem[]>(() =>
  (preds.data.value?.items || []).filter((i) => i.target_id === target.value && i.province_code === unit.value).sort((a, b) => a.lead_hours - b.lead_hours),
)

const hist = computed<SeriesData>(() => seriesOf(history.data.value?.items, target.value).filter(([t]) => t < originTime.value))
const lastObs = computed(() => [...hist.value].reverse().find(([, v]) => v != null) || null)
const future = computed<SeriesData>(() => {
  const pts: SeriesData = rows.value.map((r) => [r.valid_time, r.point_pred])
  return lastObs.value ? [[lastObs.value[0], lastObs.value[1]], ...pts] : pts
})
const mlPoint = computed<SeriesData>(() => rows.value.filter((r) => r.status.includes('ml')).map((r) => [r.valid_time, r.point_pred]))
const after = computed<SeriesData>(() =>
  ctx.replayMode === 'retrospective' ? seriesOf(actual.data.value?.items, target.value).filter(([t]) => t >= originTime.value && t <= xMax.value) : [],
)
const xMin = computed(() => (originTime.value ? addHours(originTime.value, -36) : ''))
const xMax = computed(() => (originTime.value ? addHours(originTime.value, Math.max(...horizons.value)) : ''))

const chartSummary = computed(() => {
  const head = describeSeries('起点前已知观测', hist.value, targetMeta.value?.unit || '')
  const f = rows.value.map((r) => `+${r.lead_hours}h ${fmtNum(r.point_pred, 2)}（${methodText(r)}）`).join('，')
  return `${head}；预测：${f || '无'}`
})

function methodText(r: PredictionItem) {
  if (r.status.includes('ml')) return r.status.startsWith('demo') ? '树模型（模拟数据实验）' : '树模型'
  if (r.status === 'insufficient_data') return '数据不足'
  return '朴素基线'
}

function trendText(r: PredictionItem) {
  if (r.point_pred == null || !lastObs.value || lastObs.value[1] == null) return { text: '—', cls: '' }
  const diff = r.point_pred - lastObs.value[1]
  if (Math.abs(diff) < 1e-9) return { text: '持平', cls: '' }
  return diff > 0 ? { text: '高于最后观测 ↑', cls: 'up' } : { text: '低于最后观测 ↓', cls: 'down' }
}

const h3 = computed(() => rows.value.find((r) => r.lead_hours === mlHorizon.value))

function chooseOrigin(e: Event) {
  origin.value = (e.target as HTMLSelectElement).value
}

async function runPrediction() {
  const value = customOrigin.value ? hourFloor(`${customOrigin.value}:00`) : originTime.value || ctx.cursor || ''
  if (!value || ctx.eventId == null) return
  runState.value = { status: 'running', text: `正在以 ${fmtTime(value)} 为起点运行…` }
  try {
    const res = await api.runPrediction({ dataset_id: ctx.datasetId, event_id: ctx.eventId, origin_time: value })
    runState.value = { status: res.status === 'success' ? 'done' : 'failed', text: `任务 #${res.task_id}：${res.status}` }
    origin.value = value
    customOrigin.value = ''
    await preds.reload()
  } catch (e) {
    runState.value = { status: 'failed', text: errorText(e) }
  }
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>未来影响预测</h1>
      <span class="tag attn">未经跨事件验证</span>
      <span class="muted small">只有提前 {{ mlHorizon }} 小时使用树模型，其余提前量为朴素基线；预测不能替代业务判断。</span>
    </div>
    <ContextGate>
      <div class="params">
        <label class="field">
          <span>目标</span>
          <select v-model="target" class="input">
            <option v-for="t in targets" :key="t.id" :value="t.id">{{ t.name }}</option>
          </select>
        </label>
        <label class="field">
          <span>起点</span>
          <select class="input" :value="origin || run?.origin_time || ''" @change="chooseOrigin">
            <option v-for="o in preds.data.value?.available_origins || []" :key="o" :value="o">{{ fmtTime(o) }}</option>
          </select>
        </label>
        <label class="field">
          <span>新起点</span>
          <input v-model="customOrigin" class="input" type="datetime-local" step="3600" :min="ctx.event?.start_time.slice(0, 16)" :max="ctx.event?.end_time.slice(0, 16)" />
        </label>
        <div class="field">
          <span>提前量</span>
          <div class="seg" role="group" aria-label="提前量">
            <button v-for="h in horizons" :key="h" type="button" :class="{ on: lead === h }" @click="lead = h">{{ h }} 小时</button>
          </div>
        </div>
        <button type="button" class="btn primary run" :disabled="runState.status === 'running'" @click="runPrediction">运行预测</button>
      </div>
      <p v-if="runState.text" class="note small" :class="runState.status === 'failed' ? 'bad' : 'info'" role="status">{{ runState.text }}</p>

      <StatusNote
        :status="preds.status.value"
        :error="preds.error.value"
        :stale="preds.stale.value"
        :empty="!run"
        empty-text="该事件还没有预测运行记录，选择新起点后点击“运行预测”。"
        @retry="preds.reload"
      />

      <section v-if="run" aria-label="预测曲线">
        <div class="section-head">
          <h2>{{ targetMeta?.name }}（{{ targetMeta?.unit }}） · {{ provinceName(unit) }}</h2>
          <span class="muted small">横轴同时包含起点前观测与起点后预测时段</span>
        </div>
        <TrendChart
          :series="[
            { name: '起点前已知观测', data: hist, color: COLORS.obs },
            { name: '未来预测', data: future, color: COLORS.accent, dashed: true, symbol: true },
            { name: `h${mlHorizon} 树模型点`, data: mlPoint, color: COLORS.violet, type: 'scatter' },
            ...(after.length ? [{ name: '事后实际（复盘对照）', data: after, color: COLORS.muted }] : []),
          ]"
          :axes="[{ name: targetMeta?.unit || '' }]"
          :markers="[{ time: originTime, label: '预测起点', color: '#2563EB' }]"
          :x-min="xMin"
          :x-max="xMax"
          :height="320"
          :summary="chartSummary"
          aria-label="历史观测与未来预测"
        />
        <p class="note small">区间：{{ preds.data.value?.interval_reason }}。图中不绘制不确定性阴影。</p>

        <div class="prov small">
          <span><b>运行</b> #{{ run.id }}</span>
          <span><b>数据版本</b> {{ rows[0]?.data_version || '—' }}</span>
          <span><b>模型版本</b> {{ run.model_version }}</span>
          <span><b>h{{ mlHorizon }} 训练截止</b> {{ fmtTime(h3?.train_cutoff) }}</span>
          <span><b>跨事件验证</b> {{ preds.data.value?.cross_event_validated ? '已验证' : '未验证' }}</span>
          <span><b>起点</b> {{ fmtTime(run.origin_time) }}</span>
        </div>

        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>提前量</th>
                <th>预测时刻</th>
                <th>预测值（{{ targetMeta?.unit }}）</th>
                <th>方法</th>
                <th>相对最后观测</th>
                <th>说明</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in rows" :key="r.lead_hours" :class="{ sel: r.lead_hours === lead }">
                <td>{{ r.lead_hours }} 小时</td>
                <td class="num">{{ fmtTime(r.valid_time) }}</td>
                <td class="num">{{ fmtNum(r.point_pred, 2) }}</td>
                <td>{{ methodText(r) }}</td>
                <td :class="trendText(r).cls">{{ trendText(r).text }}</td>
                <td class="muted small">{{ r.reason || '—' }}</td>
              </tr>
              <tr v-if="!rows.length">
                <td colspan="6" class="muted">该起点没有 {{ provinceName(unit) }} 的预测结果。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </ContextGate>
  </div>
</template>

<style scoped>
.params {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px 18px;
  margin-bottom: 14px;
}
.run {
  margin-left: auto;
  min-width: 120px;
  justify-content: center;
}
.prov {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 22px;
  padding: 10px 0;
  margin: 10px 0;
  border-top: 1px solid var(--line);
  border-bottom: 1px solid var(--line);
  color: #334155;
}
.prov b {
  font-weight: 600;
  color: var(--muted);
  margin-right: 4px;
}
tr.sel td {
  background: var(--accent-soft);
}
.up {
  color: #b8661a;
}
.down {
  color: var(--accent);
}
</style>
