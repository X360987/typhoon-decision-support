<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from '../api/client'
import type { ReviewAction } from '../api/types'
import ContextGate from '../components/ContextGate.vue'
import StatusNote from '../components/StatusNote.vue'
import { useLoader } from '../composables/useLoader'
import { dimensionNames, REVIEW_NAMES, SCOPE_NAMES, anomalyName, errorText, fmtNum, fmtTime, provinceName } from '../lib/format'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const route = useRoute()
const router = useRouter()

const scope = ref('')
const dimension = ref('')
const page = ref(1)
const PAGE_SIZE = 20
const tab = ref<'basis' | 'raw' | 'history'>('basis')
const note = ref('')
const submitting = ref(false)
const feedback = ref<{ ok: boolean; text: string } | null>(null)

const selectedId = computed(() => (route.params.id ? Number(route.params.id) : null))
const filters = computed(() => ({ ...ctx.params, analysis_scope: scope.value || undefined, dimension: dimension.value || undefined }))

watch([() => ctx.key, scope, dimension], () => {
  page.value = 1
})

const list = useLoader(
  (signal) => api.anomalies({ ...filters.value, page: page.value, page_size: PAGE_SIZE }, signal),
  () => [ctx.key, scope.value, dimension.value, page.value],
  { scope: () => ctx.scopeKey, enabled: () => ctx.ready },
)

const detail = useLoader(
  (signal) =>
    api.anomalyDetail(
      selectedId.value as number,
      { dataset_id: ctx.datasetId, replay_mode: ctx.replayMode, as_of: ctx.strict ? ctx.cursor : undefined },
      signal,
    ),
  () => [selectedId.value, ctx.key],
  { scope: () => `${ctx.scopeKey}|${selectedId.value}`, enabled: () => ctx.ready && selectedId.value != null },
)

// Detail must belong to the current dataset and event; otherwise it is dropped instead of shown beside another event's list.
const d = computed(() => {
  const v = detail.data.value
  if (!v || v.anomaly.id !== selectedId.value) return null
  if (v.anomaly.dataset_id !== ctx.datasetId || v.anomaly.event_id !== ctx.eventId) return null
  return v
})
const mismatch = computed(() => {
  const v = detail.data.value
  return !!v && (v.anomaly.dataset_id !== ctx.datasetId || v.anomaly.event_id !== ctx.eventId)
})

watch(
  () => ctx.scopeKey,
  (now, before) => {
    if (before && now !== before && selectedId.value != null) void router.replace({ name: 'evidence' })
  },
)

watch(
  () => list.data.value,
  (v) => {
    if (selectedId.value == null && v?.items.length && window.matchMedia('(min-width: 1100px)').matches) {
      void router.replace({ name: 'evidence', params: { id: v.items[0].id } })
    }
  },
)

watch(selectedId, () => {
  note.value = ''
  feedback.value = null
  tab.value = 'basis'
})

const totalPages = computed(() => Math.max(1, Math.ceil((list.data.value?.total || 0) / PAGE_SIZE)))
const rawEvidence = computed(() => (d.value?.evidences || []).filter((e) => e.source))
const metricEvidence = computed(() => (d.value?.evidences || []).filter((e) => !e.source))

function select(id: number) {
  void router.push({ name: 'evidence', params: { id } })
}

function onKey(e: KeyboardEvent, index: number) {
  const items = list.data.value?.items || []
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    const next = items[index + (e.key === 'ArrowDown' ? 1 : -1)]
    if (next) {
      select(next.id)
      const el = document.querySelector<HTMLElement>(`[data-anomaly="${next.id}"]`)
      el?.focus()
    }
  }
}

async function submit(action: ReviewAction) {
  if (!d.value) return
  submitting.value = true
  feedback.value = null
  try {
    const res = await api.review({ dataset_id: ctx.datasetId, target_type: 'anomaly', target_id: d.value.anomaly.id, action, note: note.value || undefined })
    feedback.value = { ok: true, text: `已记录「${REVIEW_NAMES[action]}」（操作者 ${res.operator}，${fmtTime(res.created_at)}）` }
    note.value = ''
    await Promise.all([detail.reload(), list.reload()])
  } catch (e) {
    feedback.value = { ok: false, text: errorText(e) }
  } finally {
    submitting.value = false
  }
}

const exportHref = computed(() => api.exportUrl('anomalies', filters.value))
</script>

<template>
  <div class="page evidence">
    <ContextGate>
      <div class="split">
        <section class="list-col" aria-labelledby="list-title">
          <div class="list-head">
            <h2 id="list-title">异常事件列表</h2>
            <a class="small" :href="exportHref" download>导出 CSV</a>
          </div>
          <div class="filters">
            <select v-model="scope" class="input" aria-label="分析范围">
              <option value="">全部范围</option>
              <option value="single">单维</option>
              <option value="pair">两维关系</option>
              <option value="joint">三维联合</option>
            </select>
            <select v-model="dimension" class="input" aria-label="维度">
              <option value="">全部维度</option>
              <option value="social">社会</option>
              <option value="organizational">组织</option>
              <option value="physical">物理</option>
            </select>
          </div>
          <p class="muted small">
            共 {{ list.data.value?.total ?? 0 }} 条 · 按时间倒序
            <template v-if="list.data.value?.pending_window"> · {{ list.data.value.pending_window }} 条滞后窗口未成熟（待确认，未列出）</template>
          </p>
          <StatusNote
            :status="list.status.value"
            :error="list.error.value"
            :stale="list.stale.value"
            :empty="!list.data.value?.items.length"
            empty-text="当前条件下没有异常。"
            @retry="list.reload"
          />
          <ul class="items" role="listbox" aria-label="异常列表（上下方向键切换）">
            <li v-for="(a, i) in list.data.value?.items || []" :key="a.id">
              <button
                type="button"
                class="item"
                role="option"
                :data-anomaly="a.id"
                :aria-selected="a.id === selectedId"
                :class="{ on: a.id === selectedId }"
                @click="select(a.id)"
                @keydown="onKey($event, i)"
              >
                <span class="row1"><span class="num">{{ fmtTime(a.hour_bj) }}</span><span>{{ provinceName(a.province_code) }}</span></span>
                <span class="title">{{ anomalyName(a.anomaly_type) }}</span>
                <span class="row1 small">
                  <span class="muted">{{ SCOPE_NAMES[a.analysis_scope] }} · {{ dimensionNames(a.dimensions, '/') }}</span>
                  <span :class="['rv', a.review_status]">{{ REVIEW_NAMES[a.review_status] || a.review_status }}</span>
                </span>
              </button>
            </li>
          </ul>
          <div class="pager">
            <button type="button" class="btn" :disabled="page <= 1" @click="page -= 1">上一页</button>
            <span class="small num">第 {{ page }} / {{ totalPages }} 页</span>
            <button type="button" class="btn" :disabled="page >= totalPages" @click="page += 1">下一页</button>
          </div>
        </section>

        <section class="detail-col" aria-live="polite">
          <p v-if="selectedId == null" class="muted">从左侧选择一条异常查看证据。</p>
          <template v-else>
            <p v-if="mismatch" class="note attn">该异常不属于当前数据集或事件，已清除详情。</p>
            <StatusNote :status="detail.status.value" :error="detail.error.value" :stale="detail.stale.value" @retry="detail.reload" />
            <template v-if="d">
              <h1>{{ provinceName(d.anomaly.province_code) }}{{ anomalyName(d.anomaly.anomaly_type) }}</h1>
              <p v-if="!d.visible_at_as_of" class="note attn">
                当时已知模式下，该结果在 {{ fmtTime(ctx.cursor) }} 尚不可见（判定可用时刻 {{ fmtTime(d.anomaly.available_at) }}）。此处为事后查看。
              </p>
              <p v-if="d.anomaly.requires_future_window" class="note info">滞后关系：需要事件后的观测窗口成熟才能确认，可用时刻 {{ fmtTime(d.anomaly.available_at) }}。</p>
              <nav class="tabs" aria-label="证据分区">
                <button type="button" :class="{ on: tab === 'basis' }" @click="tab = 'basis'">判定依据</button>
                <button type="button" :class="{ on: tab === 'raw' }" @click="tab = 'raw'">原始证据（{{ rawEvidence.length }}）</button>
                <button type="button" :class="{ on: tab === 'history' }" @click="tab = 'history'">核验记录（{{ d.reviews.length }}）</button>
              </nav>

              <div v-if="tab === 'basis'" class="pane">
                <p class="facts small">
                  <span><b>得分</b> {{ fmtNum(d.anomaly.score, 2) }}</span>
                  <span><b>基线</b> {{ fmtNum(d.anomaly.baseline, 2) }}</span>
                  <span><b>阈值</b> {{ fmtNum(d.anomaly.threshold, 2) }}</span>
                  <span><b>样本</b> {{ d.anomaly.sample?.sample_size ?? '—' }}</span>
                  <span><b>质量</b> {{ d.anomaly.quality_status }}</span>
                </p>
                <p class="explain">{{ d.anomaly.explanation }}</p>
                <h3>指标与关系证据</h3>
                <ol class="ev">
                  <li v-for="e in metricEvidence" :key="e.id">
                    <span class="tag">{{ e.evidence_type }}</span> {{ e.summary }}
                  </li>
                  <li v-if="!metricEvidence.length" class="muted">无指标证据记录。</li>
                </ol>
                <p class="facts small">
                  <span><b>小时</b> {{ fmtTime(d.anomaly.hour_bj) }}</span>
                  <span><b>可用时刻</b> {{ fmtTime(d.anomaly.available_at) }}</span>
                  <span><b>判定时刻</b> {{ fmtTime(d.anomaly.decided_at) }}</span>
                  <span><b>规则版本</b> {{ d.anomaly.rule_version }}</span>
                  <span><b>数据版本</b> {{ d.anomaly.data_version }}</span>
                  <span><b>分组</b> {{ d.anomaly.group_key }}</span>
                </p>
                <p v-if="d.anomaly.evidence_status === 'insufficient'" class="note attn">
                  证据不足：未能关联到同省同小时的原始记录，结论仅基于聚合指标，核验时需补充原文。
                </p>
                <template v-if="d.suggestions.length">
                  <h3>候选建议（需人工确认）</h3>
                  <ul class="ev">
                    <li v-for="s in d.suggestions" :key="s.id">{{ s.text }} <span class="muted small">· {{ REVIEW_NAMES[s.review_status] || s.review_status }}</span></li>
                  </ul>
                </template>
              </div>

              <div v-else-if="tab === 'raw'" class="pane">
                <p v-if="!rawEvidence.length" class="note attn">证据不足：没有可展示的原始微博或停运公告。</p>
                <article v-for="e in rawEvidence" :key="e.id" class="raw">
                  <header class="small muted">
                    <span v-if="e.source?.simulated" class="tag demo">模拟样例</span>
                    <template v-if="e.source?.kind === 'weibo'">
                      {{ e.source.account_class === 'official' ? '官方账号' : e.source.account_class === 'personal' ? '个人账号' : '账号身份未知' }}
                      · {{ e.source.user }} · 发布 {{ fmtTime(e.source.published_at) }} · 到达 {{ fmtTime(e.source.available_at) }} · 来源 {{ e.source.source_id }}
                    </template>
                    <template v-else-if="e.source">
                      停运公告 {{ e.source.record_no }} · 车次 {{ e.source.train_code }} · 获知 {{ fmtTime(e.source.known_at) }}
                    </template>
                  </header>
                  <blockquote>{{ e.source?.content || '（原文为空）' }}</blockquote>
                  <p class="small muted">
                    <template v-if="e.source?.kind === 'weibo'">
                      地区依据：{{ (e.source.region_basis || []).map((r) => `${provinceName(r.province_code)}（${r.method}）`).join('、') || '无' }}
                      <template v-if="e.source.publish_location"> · 发布地 {{ e.source.publish_location }}</template>
                    </template>
                    <template v-else-if="e.source">
                      区段 {{ (e.source.segment || []).map((x) => x || '?').join(' → ') }} · 范围依据 {{ e.source.scope_basis || '—' }} · 发布账号 {{ e.source.notice_account || '—' }}
                    </template>
                    <template v-if="e.source?.url"> · <a :href="e.source.url" target="_blank" rel="noopener noreferrer">来源链接</a></template>
                    <template v-else> · 无来源链接</template>
                  </p>
                </article>
                <p class="muted small">手机号、身份证号等敏感信息已脱敏，用户标识已截断。</p>
              </div>

              <div v-else class="pane">
                <ol class="history">
                  <li v-for="r in d.reviews" :key="r.id">
                    <span class="num">{{ fmtTime(r.created_at) }}</span> · <b>{{ REVIEW_NAMES[r.action] }}</b> · {{ r.operator || '未记录操作者' }}
                    <div v-if="r.note" class="muted">{{ r.note }}</div>
                  </li>
                  <li v-if="!d.reviews.length" class="muted">尚无核验记录。</li>
                </ol>
              </div>

              <div class="review-bar">
                <span class="label">核验结果：</span>
                <button type="button" class="btn ok" :disabled="submitting" @click="submit('approve')">✓ 核验通过</button>
                <button type="button" class="btn warn" :disabled="submitting" @click="submit('need_evidence')">◷ 待补证据</button>
                <button type="button" class="btn danger" :disabled="submitting" @click="submit('reject')">✕ 驳回</button>
                <label class="note-field">
                  <span class="sr-only">备注</span>
                  <textarea v-model="note" class="input" rows="2" maxlength="200" placeholder="核验备注（可选）"></textarea>
                  <span class="small muted count">{{ note.length }}/200</span>
                </label>
              </div>
              <p v-if="feedback" class="note small" :class="feedback.ok ? 'info' : 'bad'" role="status">{{ feedback.text }}</p>
              <p class="muted small">核验结果只记录人工判断，不自动触发发布或调度。</p>
            </template>
          </template>
        </section>
      </div>
    </ContextGate>
  </div>
</template>

<style scoped>
.evidence {
  padding-top: 0;
  padding-bottom: 0;
}
.split {
  display: grid;
  grid-template-columns: minmax(280px, 32fr) minmax(0, 68fr);
  min-height: calc(100vh - var(--top-h));
}
.list-col {
  border-right: 1px solid var(--line);
  padding: 20px 16px 20px 0;
}
.list-head {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
}
.filters {
  display: flex;
  gap: 8px;
  margin: 10px 0 6px;
}
.filters select {
  flex: 1;
}
.items {
  list-style: none;
  margin: 0;
  padding: 0;
}
.item {
  display: grid;
  gap: 2px;
  width: 100%;
  padding: 10px 12px;
  border: 0;
  border-bottom: 1px solid var(--line);
  background: none;
  text-align: left;
  cursor: pointer;
}
.item.on {
  background: var(--accent-soft);
  box-shadow: inset 3px 0 0 var(--accent);
}
.row1 {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--muted);
  font-size: 12px;
}
.title {
  font-weight: 600;
}
.rv.approve {
  color: var(--ok);
}
.rv.reject {
  color: var(--danger);
}
.rv.need_evidence {
  color: #b8661a;
}
.pager {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 12px;
}
.detail-col {
  padding: 22px 0 28px 28px;
  min-width: 0;
}
.detail-col h1 {
  margin-bottom: 10px;
}
.tabs {
  margin: 12px 0 14px;
}
.facts {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 18px;
  color: #334155;
}
.facts b {
  color: var(--muted);
  font-weight: 550;
  margin-right: 4px;
}
.explain {
  font-size: 15px;
}
.ev,
.history {
  padding-left: 18px;
}
.ev li,
.history li {
  margin: 6px 0;
}
.raw {
  padding: 10px 0 12px;
  border-bottom: 1px solid var(--line);
}
blockquote {
  margin: 8px 0;
  padding: 4px 14px;
  border-left: 3px solid var(--accent);
  font-size: 15px;
  line-height: 1.8;
}
.review-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 10px;
  margin-top: 22px;
  padding-top: 14px;
  border-top: 1px solid var(--line);
}
.label {
  font-weight: 600;
}
.note-field {
  position: relative;
  flex: 1 1 260px;
}
.count {
  position: absolute;
  right: 8px;
  bottom: 6px;
}
@media (max-width: 1100px) {
  .split {
    grid-template-columns: 1fr;
  }
  .list-col {
    border-right: 0;
    border-bottom: 1px solid var(--line);
    padding-right: 0;
  }
  .detail-col {
    padding-left: 0;
  }
}
</style>
