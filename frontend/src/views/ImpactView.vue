<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import { api } from '../api/client'
import type { ActionTask, Suggestion } from '../api/types'
import ContextGate from '../components/ContextGate.vue'
import PagerBar from '../components/PagerBar.vue'
import StatusNote from '../components/StatusNote.vue'
import { useLoader } from '../composables/useLoader'
import { usePager } from '../composables/usePager'
import { REVIEW_NAMES, errorText, fmtTime, provinceName } from '../lib/format'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const opts = { scope: () => ctx.scopeKey, enabled: () => ctx.ready }

const impact = useLoader((signal) => api.impact(ctx.params, signal), () => ctx.key, opts)
const suggestions = useLoader(
  (signal) => api.suggestions({ dataset_id: ctx.datasetId, event_id: ctx.eventId, data_version: ctx.dataVersion || undefined }, signal),
  () => ctx.key,
  opts,
)
const actions = useLoader((signal) => api.actions({ dataset_id: ctx.datasetId, event_id: ctx.eventId }, signal), () => ctx.key, opts)

const MAPPING: Record<string, { text: string; cls: string }> = {
  mapped: { text: '已映射', cls: 'ok' },
  pending_review: { text: '待核验', cls: 'attn' },
  unmapped: { text: '未映射', cls: 'bad' },
}
const PENDING_REASON: Record<string, string> = {
  segment_start_unmatched: '区段起点未在时刻表中匹配',
  segment_end_unmatched: '区段终点未在时刻表中匹配',
  timetable_version_ambiguous: '时刻表版本不唯一',
  timetable_version_not_found: '指定时刻表版本不存在',
  no_timetable: '无时刻表',
}
const STATUS: Record<ActionTask['status'], string> = {
  open: '待办',
  in_progress: '处理中',
  done: '已完成待销项',
  closed: '已销项',
  cancelled: '已取消',
}

const counts = computed(() => {
  const c = { mapped: 0, pending_review: 0, unmapped: 0 }
  for (const s of impact.data.value?.suspensions || []) c[s.mapping_status] += 1
  return c
})

const mappingFilter = ref('')
const susPager = usePager(() =>
  (impact.data.value?.suspensions || []).filter((s) => !mappingFilter.value || s.mapping_status === mappingFilter.value),
)
const runPager = usePager(() => impact.data.value?.run_instances || [])
const suggPager = usePager(() => suggestions.data.value?.items || [], 10)

const message = ref('')
const failure = ref('')
const drafts = reactive<Record<number, { owner: string; due_at: string }>>({})
const receipts = reactive<Record<number, string>>({})

function draft(s: Suggestion) {
  if (!drafts[s.id]) drafts[s.id] = { owner: '', due_at: '' }
  return drafts[s.id]
}

async function run(fn: () => Promise<unknown>, ok: string) {
  message.value = ''
  failure.value = ''
  try {
    await fn()
    message.value = ok
    await Promise.all([suggestions.reload(), actions.reload()])
  } catch (e) {
    failure.value = errorText(e)
  }
}

function review(s: Suggestion, action: 'approve' | 'reject') {
  void run(
    () => api.review({ dataset_id: ctx.datasetId, target_type: 'suggestion', target_id: s.id, action }),
    action === 'approve' ? '候选建议已核验通过，可形成行动任务。' : '候选建议已驳回。',
  )
}

function createTask(s: Suggestion) {
  const d = draft(s)
  void run(
    () =>
      api.createAction({
        dataset_id: ctx.datasetId,
        suggestion_id: s.id,
        owner: d.owner || undefined,
        due_at: d.due_at ? `${d.due_at}:00` : undefined,
      }),
    '已形成行动任务。',
  )
}

function setStatus(t: ActionTask, status: ActionTask['status']) {
  void run(
    () => api.updateAction(t.id, { dataset_id: ctx.datasetId, status, receipt: receipts[t.id] || undefined }),
    `任务 #${t.id} 状态已更新为「${STATUS[status]}」。`,
  )
}
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>影响事件与行动</h1>
      <RouterLink to="/overview" class="small">‹ 返回事件总览</RouterLink>
    </div>
    <ContextGate>
      <section aria-labelledby="sus-title">
        <div class="section-head">
          <h2 id="sus-title">停运范围</h2>
          <span class="muted small">
            已映射 {{ counts.mapped }} · 待核验 {{ counts.pending_review }} · 未映射 {{ counts.unmapped }}
            · 先按车次运行实例建立完整时间轴，再裁剪停运区段；端点无法匹配时进入待核验，不默认整线。
          </span>
          <select v-model="mappingFilter" class="input right" aria-label="按映射状态筛选">
            <option value="">全部映射状态</option>
            <option value="pending_review">只看待核验</option>
            <option value="unmapped">只看未映射</option>
            <option value="mapped">只看已映射</option>
          </select>
        </div>
        <StatusNote
          :status="impact.status.value"
          :error="impact.error.value"
          :stale="impact.stale.value"
          :empty="!impact.data.value?.suspensions.length"
          empty-text="当前条件下没有停运记录。"
          @retry="impact.reload"
        />
        <div v-if="impact.data.value?.suspensions.length" class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>公告编号</th>
                <th>车次</th>
                <th>运行日期</th>
                <th>获知时间</th>
                <th>停运区段</th>
                <th>涉及省份</th>
                <th>站点</th>
                <th>映射</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="s in susPager.rows.value" :key="s.id">
                <td class="num">{{ s.record_no }}</td>
                <td>{{ s.train_code }}</td>
                <td class="num">{{ fmtTime(s.suspension_date).slice(0, 10) }}</td>
                <td class="num">{{ fmtTime(s.known_at) }}</td>
                <td>{{ s.segment[0] || s.segment[1] ? `${s.segment[0] || '?'} → ${s.segment[1] || '?'}` : s.scope || '全程' }}</td>
                <td>{{ s.provinces.map(provinceName).join('、') || '—' }}</td>
                <td>{{ s.stations.length ? `${s.stations.length} 站：${s.stations.join('、')}` : '无站点集合' }}</td>
                <td>
                  <span class="tag" :class="MAPPING[s.mapping_status].cls">{{ MAPPING[s.mapping_status].text }}</span>
                  <div v-if="s.pending_reason" class="muted small">{{ PENDING_REASON[s.pending_reason] || s.pending_reason }}</div>
                </td>
              </tr>
              <tr v-if="!susPager.total.value">
                <td colspan="8" class="muted">该映射状态下没有停运记录。</td>
              </tr>
            </tbody>
          </table>
        </div>
        <PagerBar v-model="susPager.page.value" :pages="susPager.pages.value" :total="susPager.total.value" label="停运范围分页" />
      </section>

      <section class="section" aria-labelledby="run-title">
        <div class="section-head">
          <h2 id="run-title">车次运行实例</h2>
          <span class="muted small">去重键：车次 + 运行日期。跨省的同一运行实例只计一次。</span>
        </div>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>运行实例</th>
                <th>车次</th>
                <th>涉及省份</th>
                <th>影响起</th>
                <th>影响止</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="r in runPager.rows.value" :key="r.run_key">
                <td class="num">{{ r.run_key }}</td>
                <td>{{ r.train_code }}</td>
                <td>{{ r.provinces.map(provinceName).join('、') }}</td>
                <td class="num">{{ fmtTime(r.first_hour) }}</td>
                <td class="num">{{ fmtTime(r.last_hour) }}</td>
              </tr>
              <tr v-if="!impact.data.value?.run_instances.length">
                <td colspan="5" class="muted">无运行实例。</td>
              </tr>
            </tbody>
          </table>
        </div>
        <PagerBar v-model="runPager.page.value" :pages="runPager.pages.value" :total="runPager.total.value" label="运行实例分页" />
        <p class="note small">恢复与复运：{{ impact.data.value?.recovery.message || '未接入' }}</p>
      </section>

      <section class="section" aria-labelledby="act-title">
        <div class="section-head">
          <h2 id="act-title">候选建议与行动任务</h2>
        </div>
        <p class="note">
          候选建议由规则生成，需人工核验通过后才能形成业务行动任务。行动任务记录责任人、期限、回执与销项，与后台计算任务（TaskRun）分开；计算成功不代表处置完成。平台不自动发布、调度或认定责任。
        </p>
        <p v-if="message" class="note info" role="status">{{ message }}</p>
        <p v-if="failure" class="note bad" role="alert">操作失败：{{ failure }}</p>

        <h3 class="sub-title">候选建议</h3>
        <StatusNote
          :status="suggestions.status.value"
          :error="suggestions.error.value"
          :empty="!suggestions.data.value?.items.length"
          empty-text="当前数据版本没有候选建议。"
          @retry="suggestions.reload"
        />
        <ul class="sugg">
          <li v-for="s in suggPager.rows.value" :key="s.id">
            <div class="sugg-main">
              <span class="tag" :class="s.review_status === 'approve' ? 'ok' : s.review_status === 'reject' ? 'bad' : ''">
                {{ REVIEW_NAMES[s.review_status] || s.review_status }}
              </span>
              <strong>{{ s.suggestion_code }}</strong>
              <span>{{ s.text }}</span>
              <span v-if="s.trigger_reason" class="muted small">触发：{{ s.trigger_reason }}</span>
            </div>
            <div class="sugg-actions">
              <template v-if="s.review_status !== 'approve'">
                <button type="button" class="btn ok" @click="review(s, 'approve')">核验通过</button>
                <button v-if="s.review_status !== 'reject'" type="button" class="btn danger" @click="review(s, 'reject')">驳回</button>
              </template>
              <template v-else>
                <label class="field"><span>责任人</span><input v-model="draft(s).owner" class="input" placeholder="如：值班组" /></label>
                <label class="field"><span>期限</span><input v-model="draft(s).due_at" class="input" type="datetime-local" /></label>
                <button type="button" class="btn primary" @click="createTask(s)">形成行动任务</button>
              </template>
            </div>
          </li>
        </ul>
        <PagerBar v-model="suggPager.page.value" :pages="suggPager.pages.value" :total="suggPager.total.value" label="候选建议分页" />

        <h3 class="sub-title">行动任务</h3>
        <div class="table-wrap">
          <table class="data">
            <thead>
              <tr>
                <th>#</th>
                <th>任务</th>
                <th>责任人</th>
                <th>期限</th>
                <th>状态</th>
                <th>回执</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="t in actions.data.value?.items || []" :key="t.id">
                <td class="num">{{ t.id }}</td>
                <td>{{ t.title }}</td>
                <td>{{ t.owner || '—' }}</td>
                <td class="num">{{ fmtTime(t.due_at) }}</td>
                <td>{{ STATUS[t.status] }}</td>
                <td>
                  <span v-if="t.receipt">{{ t.receipt }}</span>
                  <input v-else-if="t.status !== 'closed' && t.status !== 'cancelled'" v-model="receipts[t.id]" class="input" placeholder="销项前填写回执" />
                </td>
                <td class="ops">
                  <button v-if="t.status === 'open'" type="button" class="btn" @click="setStatus(t, 'in_progress')">开始处理</button>
                  <button v-if="t.status === 'in_progress'" type="button" class="btn" @click="setStatus(t, 'done')">标记完成</button>
                  <button
                    v-if="t.status !== 'closed' && t.status !== 'cancelled'"
                    type="button"
                    class="btn ok"
                    :disabled="!t.receipt && !receipts[t.id]"
                    :title="!t.receipt && !receipts[t.id] ? '销项前需要填写回执' : ''"
                    @click="setStatus(t, 'closed')"
                  >
                    销项
                  </button>
                </td>
              </tr>
              <tr v-if="!actions.data.value?.items.length">
                <td colspan="7" class="muted">尚无行动任务。</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </ContextGate>
  </div>
</template>

<style scoped>
.sub-title {
  margin: 18px 0 8px;
}
.sugg {
  list-style: none;
  margin: 0;
  padding: 0;
}
.sugg li {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 18px;
  justify-content: space-between;
  padding: 10px 0;
  border-bottom: 1px solid var(--line);
}
.sugg-main {
  display: flex;
  flex-wrap: wrap;
  gap: 4px 10px;
  align-items: baseline;
  flex: 1 1 420px;
}
.sugg-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: center;
}
.ops {
  display: flex;
  gap: 6px;
}
</style>
