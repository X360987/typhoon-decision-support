<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import { api, credentials } from '../api/client'
import type { CommitResult, PrecheckReport } from '../api/types'
import StatusNote from '../components/StatusNote.vue'
import { useLoader } from '../composables/useLoader'
import { errorText, fmtTime, provinceName } from '../lib/format'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()

// ---- import stepper
const STEPS = ['选择文件', '字段映射', '预检', '确认导入']
const step = ref(0)
const entity = ref('weibo')
const importEvent = ref<number | null>(null)
const file = ref<File | null>(null)
const columns = ref<string[]>([])
const mapping = reactive<Record<string, string>>({})
const report = ref<PrecheckReport | null>(null)
const policy = ref<'strict' | 'skip_errors'>('strict')
const confirmSkip = ref(false)
const result = ref<CommitResult | null>(null)
const busy = ref(false)
const importError = ref('')

const TARGETS = [
  'source_id',
  'user_id',
  'content',
  'published_at',
  'available_at',
  'publish_location',
  'nickname',
  'topics',
  'reposts',
  'comments',
  'likes',
  'ip',
  'verify_type',
  'bid',
  'article_url',
]
const REQUIRED = ['source_id', 'user_id', 'content', 'published_at']

const sources = useLoader(() => api.importSources(), () => ctx.bootStatus, { enabled: () => ctx.bootStatus !== 'loading' })
const batches = useLoader((signal) => api.batches(ctx.datasetId, signal), () => [ctx.datasetId, ctx.revision], { enabled: () => !!ctx.datasetId })
const coverage = useLoader(
  (signal) => api.coverage({ dataset_id: ctx.datasetId, event_id: ctx.eventId, data_version: ctx.dataVersion || undefined }, signal),
  () => [ctx.scopeKey, ctx.revision],
  { enabled: () => ctx.ready },
)
const runs = useLoader((signal) => api.runs({ dataset_id: ctx.datasetId, event_id: ctx.eventId }, signal), () => [ctx.scopeKey, ctx.revision], {
  enabled: () => ctx.ready,
})

watch(
  () => ctx.eventId,
  (id) => {
    if (importEvent.value == null || !ctx.events.some((e) => e.id === importEvent.value)) importEvent.value = id
  },
  { immediate: true },
)

const mappedTargets = computed(() => columns.value.map((c) => mapping[c] || c))
const missingRequired = computed(() => REQUIRED.filter((r) => !mappedTargets.value.includes(r)))
const mappingPayload = computed(() => {
  const out: Record<string, string> = {}
  for (const c of columns.value) if (mapping[c] && mapping[c] !== c) out[c] = mapping[c]
  return out
})
const hasMapping = computed(() => Object.keys(mappingPayload.value).length > 0)
const blockingRows = computed(() => (report.value?.error_rows || []).filter((r) => r.blocking))
const canCommit = computed(() => {
  if (!report.value?.precheck_token) return false
  if (policy.value === 'strict') return report.value.ok
  return confirmSkip.value
})
const commitBlockReason = computed(() => {
  if (!report.value) return ''
  if (!report.value.precheck_token) return `预检未通过结构检查（${report.value.message || report.value.error}），不能提交。`
  if (policy.value === 'strict' && !report.value.ok) return `存在 ${report.value.blocking_errors} 行阻断错误，严格模式不能导入。可修正文件后重新预检，或改为“跳过错误行”并确认排除清单。`
  if (policy.value === 'skip_errors' && !confirmSkip.value) return '跳过错误行需要先勾选确认排除清单。'
  return ''
})

async function onFile(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0] || null
  file.value = f
  report.value = null
  result.value = null
  importError.value = ''
  columns.value = []
  for (const k of Object.keys(mapping)) delete mapping[k]
  if (f && f.name.toLowerCase().endsWith('.csv')) {
    const head = await f.slice(0, 8192).text()
    const first = head.replace(/^\ufeff/, '').split(/\r?\n/)[0] || ''
    columns.value = first.split(',').map((c) => c.trim().replace(/^"|"$/g, '')).filter(Boolean)
    for (const c of columns.value) mapping[c] = TARGETS.includes(c) ? c : ''
  }
}

function form(extra: Record<string, string>) {
  const fd = new FormData()
  if (file.value) fd.append('file', file.value)
  fd.append('dataset_id', ctx.datasetId)
  fd.append('event_id', String(importEvent.value ?? ''))
  if (hasMapping.value) fd.append('column_mapping', JSON.stringify(mappingPayload.value))
  for (const [k, v] of Object.entries(extra)) fd.append(k, v)
  return fd
}

async function runPrecheck() {
  if (!file.value || importEvent.value == null) return
  busy.value = true
  importError.value = ''
  report.value = null
  try {
    report.value = await api.precheck(form({ entity: entity.value }))
    policy.value = 'strict'
    confirmSkip.value = false
    step.value = 2
  } catch (e) {
    importError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

async function runCommit() {
  if (!report.value?.precheck_token || !canCommit.value) return
  busy.value = true
  importError.value = ''
  try {
    result.value = await api.commit(
      form({ precheck_token: report.value.precheck_token, error_policy: policy.value, confirm_skip: String(confirmSkip.value) }),
    )
    step.value = 3
    await ctx.loadEvents().catch(() => undefined)
    ctx.touch()
  } catch (e) {
    importError.value = errorText(e)
  } finally {
    busy.value = false
  }
}

function next() {
  if (columns.value.length) step.value = 1
  else void runPrecheck()
}

function resetImport() {
  step.value = 0
  file.value = null
  report.value = null
  result.value = null
  importError.value = ''
  columns.value = []
}

// ---- batch errors
const openBatch = ref<number | null>(null)
const batchErrors = ref<Array<{ row_number: number; reason: string }>>([])
async function showErrors(id: number) {
  openBatch.value = id
  batchErrors.value = []
  try {
    batchErrors.value = (await api.importErrors(id, ctx.datasetId)).items
  } catch (e) {
    batchErrors.value = [{ row_number: 0, reason: errorText(e) }]
  }
}

// ---- credentials, rerun, seed, events
const apiKey = ref(credentials.apiKey)
const operator = ref(credentials.operator)
const credSaved = ref(false)
function saveCredentials() {
  credentials.save(apiKey.value.trim(), operator.value.trim())
  credSaved.value = true
}

const opMessage = ref<{ ok: boolean; text: string } | null>(null)
async function rerun() {
  if (ctx.eventId == null) return
  opMessage.value = { ok: true, text: '正在重跑分析…' }
  try {
    const res = await api.rerun(ctx.datasetId, ctx.eventId)
    const runsOut = (res.runs as Array<{ status: string; data_version?: string; message?: string }> | undefined) || []
    const r = runsOut[0]
    opMessage.value =
      r?.status === 'success'
        ? { ok: true, text: `重跑成功，新版本 ${r.data_version} 已生效；旧版本保留可查。` }
        : { ok: false, text: `重跑失败，继续使用原版本：${r?.message || res.status}` }
    await ctx.loadEvents()
    ctx.touch()
  } catch (e) {
    opMessage.value = { ok: false, text: errorText(e) }
  }
}

async function seed() {
  opMessage.value = { ok: true, text: '正在生成模拟数据…' }
  try {
    await api.seed()
    opMessage.value = { ok: true, text: '模拟数据已生成（标注为模拟）。' }
    await ctx.bootstrap()
    ctx.touch()
  } catch (e) {
    opMessage.value = { ok: false, text: errorText(e) }
  }
}

const newEvent = reactive({ dataset_id: '', event_code: '', name: '', start_time: '', end_time: '' })
watch(
  () => [ctx.datasetId, ctx.dataMode] as const,
  ([id, mode]) => {
    if (!newEvent.dataset_id) newEvent.dataset_id = id || (mode === 'real' ? 'real' : 'demo')
  },
  { immediate: true },
)
async function createEvent() {
  try {
    const res = await api.createEvent({
      ...newEvent,
      start_time: `${newEvent.start_time}:00`,
      end_time: `${newEvent.end_time}:00`,
    })
    opMessage.value = { ok: true, text: `事件已登记（#${res.id}）。` }
    await ctx.bootstrap()
    if (ctx.datasetId === newEvent.dataset_id) ctx.selectEvent(res.id)
  } catch (e) {
    opMessage.value = { ok: false, text: errorText(e) }
  }
}

const viewingVersion = computed(
  () => ctx.dataVersion || runs.data.value?.items.find((r) => r.active)?.data_version || ctx.event?.active_version || '',
)

const matrixMetrics = ['personal_weibo_count', 'negative_ratio', 'official_weibo_count', 'unknown_account_count', 'affected_trains', 'affected_stations']
const METRIC_LABEL: Record<string, string> = {
  personal_weibo_count: '个人微博',
  negative_ratio: '负面比例',
  official_weibo_count: '官方发布',
  unknown_account_count: '未知身份',
  affected_trains: '受影响车次',
  affected_stations: '受影响站点',
}
const matrixRows = computed(() =>
  Object.entries(coverage.data.value?.metric_matrix || {}).sort(([a], [b]) => (a === 'ALL' ? -1 : b === 'ALL' ? 1 : a.localeCompare(b))),
)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>数据导入与质量</h1>
      <RouterLink class="small" to="/data/glossary">资料与口径 ›</RouterLink>
      <span class="tag" :class="ctx.dataMode === 'real' ? 'real' : 'demo'">{{ ctx.dataMode === 'real' ? '真实模式' : '模拟模式' }}</span>
    </div>

    <ol class="stepper" aria-label="导入步骤">
      <li v-for="(s, i) in STEPS" :key="s" :class="{ done: i < step, on: i === step }" :aria-current="i === step ? 'step' : undefined">
        <span class="circle">{{ i + 1 }}</span>{{ s }}
      </li>
    </ol>

    <p v-if="!ctx.datasetId" class="note">当前没有数据集。请先在下方登记事件（会同时创建数据集），再导入文件。</p>

    <section v-if="step === 0" class="import-step">
      <div class="row">
        <label class="field">
          <span>数据来源</span>
          <select v-model="entity" class="input">
            <option v-for="s in sources.data.value?.items || []" :key="s.entity" :value="s.entity" :disabled="s.status !== 'supported'">
              {{ s.name }}{{ s.status !== 'supported' ? '（未接入）' : '' }}
            </option>
          </select>
        </label>
        <label class="field">
          <span>归属事件</span>
          <select v-model="importEvent" class="input" :disabled="!ctx.events.length">
            <option v-for="e in ctx.events" :key="e.id" :value="e.id">{{ e.name }}</option>
          </select>
        </label>
        <label class="field">
          <span>文件</span>
          <input class="input" type="file" accept=".csv,.xlsx,.xls" @change="onFile" />
        </label>
      </div>
      <p class="muted small">
        支持 CSV / XLSX，单文件不超过 {{ sources.data.value?.max_upload_mb ?? 20 }} MB。必填字段：{{ REQUIRED.join('、') }}；建议提供 available_at（数据实际到达时间），否则导入后不能用于当时已知回放。模板见后端
        data/templates/weibo_template.csv。
      </p>
      <ul class="sources small">
        <li v-for="s in sources.data.value?.items || []" :key="s.entity">
          {{ s.name }}：<span :class="s.status === 'supported' ? 'ok-text' : 'muted'">{{ s.status === 'supported' ? '已接入' : '未接入' }}</span>
        </li>
      </ul>
      <button type="button" class="btn primary" :disabled="!file || importEvent == null || busy" @click="next">下一步</button>
    </section>

    <section v-else-if="step === 1" class="import-step">
      <h2>字段映射 · {{ file?.name }}</h2>
      <p class="muted small">左侧为文件列名，右侧选择对应的平台字段；留空表示保持原列名。</p>
      <div class="table-wrap narrow">
        <table class="data">
          <thead>
            <tr>
              <th>文件列</th>
              <th>平台字段</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="c in columns" :key="c">
              <td>{{ c }}</td>
              <td>
                <select v-model="mapping[c]" class="input">
                  <option value="">（保持原名）</option>
                  <option v-for="t in TARGETS" :key="t" :value="t">{{ t }}{{ REQUIRED.includes(t) ? ' *' : '' }}</option>
                </select>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="missingRequired.length" class="note attn">尚未映射必填字段：{{ missingRequired.join('、') }}。预检会报告缺失字段并拒绝提交。</p>
      <div class="actions">
        <button type="button" class="btn" @click="step = 0">返回</button>
        <button type="button" class="btn primary" :disabled="busy" @click="runPrecheck">运行预检</button>
      </div>
    </section>

    <section v-else-if="step === 2" class="import-step">
      <div class="file-head">
        <h2>{{ report?.file_name || file?.name }}</h2>
        <span v-if="report" class="muted">
          {{ report.rows }} 行 / <span :class="{ bad: report.blocking_errors }">{{ report.blocking_errors }} 行阻断错误</span> / {{ report.duplicates }} 行重复 /
          {{ report.warnings }} 行警告
        </span>
      </div>
      <p v-if="busy" class="muted">预检中…</p>
      <div v-if="report" class="precheck-grid">
        <div>
          <div class="table-wrap">
            <table class="data">
              <thead>
                <tr>
                  <th>行号</th>
                  <th>发布时间</th>
                  <th>地区</th>
                  <th>内容</th>
                  <th>检查结果</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in report.preview" :key="r.row">
                  <td class="num">{{ r.row }}</td>
                  <td class="num" :class="{ bad: !r.published_at }">{{ r.published_at ? fmtTime(r.published_at) : '无法解析' }}</td>
                  <td>{{ r.publish_location || '—' }}</td>
                  <td>{{ r.content }}</td>
                  <td>
                    <span v-if="r.status === 'ok'" class="ok-text">✓ 正常</span>
                    <span v-else-if="r.status === 'error'" class="bad">! {{ report.error_rows.find((e) => e.row === r.row)?.reasons.join('；') }}</span>
                    <span v-else-if="r.status === 'duplicate'" class="warn-text">重复，不导入</span>
                    <span v-else class="warn-text">{{ report.error_rows.find((e) => e.row === r.row)?.reasons.join('；') }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <p v-if="report.rows > report.preview.length" class="muted small">仅预览前 {{ report.preview.length }} 行；错误清单覆盖全部行。</p>

          <fieldset class="policy">
            <legend>错误行策略</legend>
            <label><input v-model="policy" type="radio" value="strict" :disabled="!report.precheck_token" /> 严格：有阻断错误则不导入</label>
            <label><input v-model="policy" type="radio" value="skip_errors" :disabled="!report.allowed_policies.includes('skip_errors')" /> 跳过错误行：其余行导入，错误行记录到批次</label>
            <div v-if="policy === 'skip_errors' && blockingRows.length" class="skip-list">
              <p class="small">将排除以下 {{ blockingRows.length }} 行：</p>
              <ul class="small">
                <li v-for="r in blockingRows.slice(0, 20)" :key="r.row">第 {{ r.row }} 行：{{ r.reasons.join('；') }}</li>
                <li v-if="blockingRows.length > 20" class="muted">…另有 {{ blockingRows.length - 20 }} 行</li>
              </ul>
              <label><input v-model="confirmSkip" type="checkbox" /> 我已核对排除清单，确认只导入其余行</label>
            </div>
          </fieldset>

          <p v-if="commitBlockReason" class="note attn" role="status">{{ commitBlockReason }}</p>
          <div class="actions">
            <button type="button" class="btn" @click="step = columns.length ? 1 : 0">返回{{ columns.length ? '映射' : '' }}</button>
            <button type="button" class="btn primary" :disabled="!canCommit || busy" @click="runCommit">确认导入</button>
          </div>
        </div>
        <aside class="quality">
          <h3>数据质量检查</h3>
          <ul>
            <li v-for="c in report.checks" :key="c.name" :class="c.status">
              <span class="icon" aria-hidden="true">{{ c.status === 'pass' ? '✓' : '!' }}</span>
              <div>
                <strong>{{ c.name }}</strong>
                <div class="small muted">{{ c.status === 'pass' ? '通过' : c.status === 'warn' ? '警告' : '未通过' }} · {{ c.detail }}</div>
              </div>
            </li>
          </ul>
          <p v-if="report.time_range" class="small muted">时间范围 {{ fmtTime(report.time_range.start) }} ~ {{ fmtTime(report.time_range.end) }}</p>
        </aside>
      </div>
    </section>

    <section v-else class="import-step">
      <h2>导入结果</h2>
      <dl v-if="result" class="result">
        <dt>导入状态</dt>
        <dd>{{ result.import_status === 'idempotent_reuse' ? '同一文件已导入过，复用原批次（未重复写入）' : '已导入' }} · 批次 #{{ result.batch_id }}</dd>
        <dt>写入 / 跳过重复</dt>
        <dd>{{ result.inserted ?? '—' }} / {{ result.skipped ?? '—' }}</dd>
        <dt>分析状态</dt>
        <dd>
          <span class="tag" :class="result.analysis_status === 'success' ? 'ok' : 'bad'">
            {{ result.analysis_status === 'success' ? '分析成功，新版本已生效' : `分析失败（${result.analysis_status}），继续使用原版本，可在下方重跑` }}
          </span>
        </dd>
      </dl>
      <button type="button" class="btn" @click="resetImport">继续导入</button>
    </section>
    <p v-if="importError" class="note bad" role="alert">{{ importError }}</p>

    <section class="section" aria-labelledby="batch-title">
      <div class="section-head"><h2 id="batch-title">近期导入历史</h2></div>
      <StatusNote :status="batches.status.value" :error="batches.error.value" :empty="!batches.data.value?.items.length" empty-text="暂无导入批次。" @retry="batches.reload" />
      <div v-if="batches.data.value?.items.length" class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>批次</th>
              <th>文件</th>
              <th>来源</th>
              <th>导入时间</th>
              <th>写入</th>
              <th>排除行</th>
              <th>导入状态</th>
              <th>分析状态</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="b in batches.data.value.items" :key="b.id">
              <td class="num">#{{ b.id }}</td>
              <td>{{ b.file_name || '—' }}</td>
              <td>{{ b.source_type }}</td>
              <td class="num">{{ fmtTime(b.created_at) }}</td>
              <td class="num">{{ b.inserted ?? '—' }}</td>
              <td class="num">{{ b.excluded_rows }}</td>
              <td>{{ b.status }}</td>
              <td>{{ b.analysis_status || '—' }}</td>
              <td><button v-if="b.excluded_rows" type="button" class="btn ghost" @click="showErrors(b.id)">错误行</button></td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="openBatch != null" class="errors">
        <h3>批次 #{{ openBatch }} 错误行</h3>
        <ul class="small">
          <li v-for="e in batchErrors" :key="e.row_number">第 {{ e.row_number }} 行：{{ e.reason }}</li>
        </ul>
      </div>
    </section>

    <section v-if="ctx.ready" class="section" aria-labelledby="cov-title">
      <div class="section-head">
        <h2 id="cov-title">覆盖与质量 · {{ ctx.event?.name }}</h2>
        <span class="muted small">事件共 {{ coverage.data.value?.event_hours ?? '—' }} 小时；单元格为“有观测小时 / 样本数”</span>
      </div>
      <StatusNote :status="coverage.status.value" :error="coverage.error.value" @retry="coverage.reload" />
      <div v-if="coverage.data.value" class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>省份</th>
              <th v-for="m in matrixMetrics" :key="m">{{ METRIC_LABEL[m] }}</th>
              <th>低样本小时</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="[prov, row] in matrixRows" :key="prov">
              <td>{{ provinceName(prov) }}</td>
              <td v-for="m in matrixMetrics" :key="m" class="num" :class="{ missing: !row[m] }">
                {{ row[m] ? `${row[m].hours} / ${row[m].samples}` : '缺测' }}
              </td>
              <td class="num">{{ coverage.data.value.low_sample_hours[prov] ?? 0 }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <ul v-if="coverage.data.value" class="facts small">
        <li>账号身份：个人 {{ coverage.data.value.account_classes.personal ?? 0 }} · 官方 {{ coverage.data.value.account_classes.official ?? 0 }} · 未知 {{ coverage.data.value.account_classes.unknown ?? 0 }}（未知身份不计入个人或官方统计）</li>
        <li>到达时间未知的指标行：{{ coverage.data.value.unknown_arrival_metric_rows }}（当时已知回放中不可用）</li>
        <li>停运待核验：{{ coverage.data.value.pending_mapping.length }} 条 <template v-for="p in coverage.data.value.pending_mapping" :key="p.suspension_id">· {{ p.record_no }}（{{ p.reason }}）</template></li>
        <li v-for="p in coverage.data.value.proxy_sources" :key="p.metric">代理值：{{ p.metric }}——{{ p.note }}</li>
      </ul>
    </section>

    <section v-if="ctx.ready" class="section" aria-labelledby="ver-title">
      <div class="section-head">
        <h2 id="ver-title">分析版本</h2>
        <span class="muted small">每次分析生成新版本，全部阶段成功后才切换；失败时保留原版本。</span>
        <button type="button" class="btn right" @click="rerun">重跑当前事件</button>
      </div>
      <div class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>运行</th>
              <th>数据版本</th>
              <th>状态</th>
              <th>触发</th>
              <th>规则版本</th>
              <th>完成时间</th>
              <th>查看</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in runs.data.value?.items || []" :key="r.id">
              <td class="num">#{{ r.id }}</td>
              <td>{{ r.data_version || '—' }} <span v-if="r.active" class="tag ok">生效</span></td>
              <td>
                <span class="tag" :class="r.status === 'success' ? 'ok' : r.status === 'failed' ? 'bad' : ''">{{ r.status }}</span>
                <div v-if="r.message" class="muted small">{{ r.message }}</div>
              </td>
              <td>{{ r.trigger }}</td>
              <td>{{ r.rule_version }}</td>
              <td class="num">{{ fmtTime(r.finished_at) }}</td>
              <td>
                <button
                  v-if="r.data_version && r.status === 'success'"
                  type="button"
                  class="btn ghost"
                  :aria-pressed="viewingVersion === r.data_version"
                  @click="ctx.dataVersion = r.active ? '' : r.data_version"
                >
                  {{ viewingVersion === r.data_version ? '当前查看' : '切换查看' }}
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p v-if="ctx.dataVersion" class="note info">正在查看历史版本 {{ ctx.dataVersion }}，全站页面同步使用该版本。<button type="button" class="btn ghost" @click="ctx.dataVersion = ''">回到生效版本</button></p>
    </section>

    <p v-if="opMessage" class="note" :class="opMessage.ok ? 'info' : 'bad'" role="status">{{ opMessage.text }}</p>

    <section class="section settings" aria-labelledby="set-title">
      <h2 id="set-title">写操作与事件登记</h2>
      <div class="settings-grid">
        <form class="block" @submit.prevent="saveCredentials">
          <h3>写操作凭证</h3>
          <p class="muted small">
            {{ ctx.health?.write_requires_key ? '服务端要求 X-API-Key 才能导入、重跑、预测、核验或登记事件。' : '服务端未配置 API_KEY（仅模拟模式允许免密写入）。' }}
            凭证只保存在当前浏览器标签页（sessionStorage）。
          </p>
          <label class="field"><span>API Key</span><input v-model="apiKey" class="input" type="password" autocomplete="off" /></label>
          <label class="field"><span>操作者</span><input v-model="operator" class="input" placeholder="记录在核验与任务中" /></label>
          <button type="submit" class="btn">保存</button>
          <span v-if="credSaved" class="small ok-text">已保存</span>
        </form>

        <form class="block" @submit.prevent="createEvent">
          <h3>登记台风事件</h3>
          <label class="field"><span>数据集</span><input v-model="newEvent.dataset_id" class="input" required /></label>
          <label class="field"><span>事件编号</span><input v-model="newEvent.event_code" class="input" required /></label>
          <label class="field"><span>名称</span><input v-model="newEvent.name" class="input" required /></label>
          <label class="field"><span>开始</span><input v-model="newEvent.start_time" class="input" type="datetime-local" required /></label>
          <label class="field"><span>结束</span><input v-model="newEvent.end_time" class="input" type="datetime-local" required /></label>
          <button type="submit" class="btn">登记</button>
        </form>

        <div v-if="ctx.health?.seed_allowed" class="block">
          <h3>模拟数据</h3>
          <p class="muted small">仅模拟模式可用。生成的数据全部标注为模拟，用于演示流程，不代表真实情况。</p>
          <button type="button" class="btn" @click="seed">生成 / 重置模拟数据</button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.stepper {
  display: flex;
  list-style: none;
  padding: 0;
  margin: 0 0 22px;
  gap: 0;
}
.stepper li {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--muted);
  font-weight: 550;
}
.stepper li:not(:last-child)::after {
  content: '';
  flex: 1;
  height: 1px;
  background: var(--line-strong);
  margin: 0 14px;
}
.circle {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 1px solid var(--line-strong);
  display: inline-grid;
  place-items: center;
  background: #fff;
}
.stepper li.on {
  color: var(--text);
}
.stepper li.on .circle {
  background: var(--obs);
  border-color: var(--obs);
  color: #fff;
}
.stepper li.done .circle {
  border-color: var(--obs);
  color: var(--obs);
}
.import-step {
  display: grid;
  gap: 12px;
}
.import-step > .btn,
.block > .btn {
  justify-self: start;
}
.row {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
}
.sources {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 16px;
  list-style: none;
  padding: 0;
  margin: 0;
}
.narrow {
  max-width: 560px;
}
.actions {
  display: flex;
  gap: 10px;
  margin-top: 6px;
}
.file-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 14px;
}
.precheck-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 260px;
  gap: 26px;
}
.quality {
  border-left: 1px solid var(--line);
  padding-left: 20px;
}
.quality ul {
  list-style: none;
  padding: 0;
}
.quality li {
  display: flex;
  gap: 10px;
  margin: 12px 0;
}
.quality .icon {
  width: 22px;
  height: 22px;
  flex: none;
  border-radius: 50%;
  display: grid;
  place-items: center;
  color: #fff;
  font-size: 12px;
  background: var(--ok);
}
.quality li.warn .icon {
  background: var(--attn);
}
.quality li.fail .icon {
  background: var(--danger);
}
.policy {
  margin-top: 14px;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 10px 14px;
  display: grid;
  gap: 6px;
}
.skip-list {
  padding: 6px 0 0 20px;
}
.bad {
  color: var(--danger);
}
.ok-text {
  color: var(--ok);
}
.warn-text {
  color: #b8661a;
}
.missing {
  color: var(--faint);
}
.result {
  display: grid;
  grid-template-columns: 140px 1fr;
  gap: 6px 14px;
  margin: 0;
}
.result dt {
  color: var(--muted);
}
.result dd {
  margin: 0;
}
.facts {
  margin-top: 10px;
  padding-left: 18px;
  color: #334155;
}
.errors {
  margin-top: 10px;
}
.settings-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 26px;
  margin-top: 12px;
}
.block {
  display: grid;
  gap: 8px;
  align-content: start;
}
.block .field {
  justify-content: space-between;
}
.block .field .input {
  flex: 1;
  max-width: 240px;
}
@media (max-width: 1100px) {
  .precheck-grid {
    grid-template-columns: 1fr;
  }
  .quality {
    border-left: 0;
    padding-left: 0;
  }
}
@media (max-width: 760px) {
  .stepper {
    flex-wrap: wrap;
    gap: 8px;
  }
  .stepper li::after {
    display: none;
  }
}
</style>
