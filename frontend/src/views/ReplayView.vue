<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api/client'
import type { TimelineItem } from '../api/types'
import ContextGate from '../components/ContextGate.vue'
import ProvinceMap from '../components/ProvinceMap.vue'
import StatusNote from '../components/StatusNote.vue'
import TimeAxis from '../components/TimeAxis.vue'
import TrendChart from '../components/TrendChart.vue'
import { useLoader } from '../composables/useLoader'
import { addHours, fmtTime, provinceName } from '../lib/format'
import { COLORS, describeSeries, seriesOf } from '../lib/series'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()
const router = useRouter()
const opts = { scope: () => ctx.scopeKey, enabled: () => ctx.ready }

const METRICS = 'personal_weibo_count,help_request_count,official_weibo_count,affected_trains,affected_stations'
const lanes = useLoader(
  (signal) => api.metrics({ ...ctx.params, province_code: ctx.province || 'ALL', metric_id: METRICS }, signal),
  () => ctx.key,
  opts,
)
const locator = useLoader(
  (signal) => api.summary({ ...ctx.params, province_code: undefined, hour_bj: ctx.cursor }, signal),
  () => [ctx.key, ctx.cursor],
  opts,
)
const LOG_BEFORE = 12
const LOG_AFTER = 6
const log = useLoader(
  (signal) =>
    api.timeline(
      {
        ...ctx.params,
        known_from: ctx.cursor ? addHours(ctx.cursor, -LOG_BEFORE) : undefined,
        known_to: ctx.cursor ? (ctx.strict ? ctx.cursor : addHours(ctx.cursor, LOG_AFTER)) : undefined,
        limit: 300,
      },
      signal,
    ),
  () => [ctx.key, ctx.cursor],
  opts,
)

const items = computed(() => lanes.data.value?.items)
const personal = computed(() => seriesOf(items.value, 'personal_weibo_count'))
const help = computed(() => seriesOf(items.value, 'help_request_count'))
const official = computed(() => seriesOf(items.value, 'official_weibo_count'))
const trains = computed(() => seriesOf(items.value, 'affected_trains'))
const stations = computed(() => seriesOf(items.value, 'affected_stations'))

const summary = computed(() =>
  [
    ctx.strict ? `当时已知（截至 ${fmtTime(ctx.cursor)}）` : `事后复盘（游标 ${fmtTime(ctx.cursor)}）`,
    describeSeries('社会·个人微博', personal.value, '条'),
    describeSeries('组织·官方发布', official.value, '条'),
    describeSeries('物理·受影响车次', trains.value, '列'),
  ].join('；'),
)

const KIND: Record<TimelineItem['kind'], { label: string; color: string }> = {
  official_post: { label: '官方发布', color: COLORS.accent },
  suspension_notice: { label: '停运公告', color: COLORS.attn },
  anomaly: { label: '异常判定', color: COLORS.danger },
}

const logItems = computed(() => (log.data.value?.items || []).slice().sort((a, b) => (a.known_at || a.time || '').localeCompare(b.known_at || b.time || '')))

function afterCursor(it: TimelineItem) {
  return !!ctx.cursor && !!it.known_at && it.known_at > ctx.cursor
}

function openRef(it: TimelineItem) {
  const [table, id] = it.ref.split(':')
  if (table === 'anomaly') void router.push({ name: 'evidence', params: { id } })
}

const locatorCard = computed(() => locator.data.value?.cards?.physical_trains)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <h1>历史回放</h1>
      <div class="seg mode" role="group" aria-label="回放模式">
        <button type="button" :class="{ on: ctx.replayMode === 'as_known' }" @click="ctx.replayMode = 'as_known'">当时已知</button>
        <button type="button" :class="{ on: ctx.replayMode === 'retrospective' }" @click="ctx.replayMode = 'retrospective'">事后复盘</button>
      </div>
      <span class="muted small">
        {{
          ctx.replayMode === 'as_known'
            ? `只显示 ${fmtTime(ctx.cursor)} 之前已到达的数据，游标之后不绘制观测。`
            : `事后完整复盘，游标定位到 ${fmtTime(ctx.cursor)}；图中游标之后的数据在当时尚未获知。`
        }}
      </span>
    </div>
    <ContextGate>
      <div class="replay-grid">
        <section aria-label="三维泳道">
          <StatusNote :status="lanes.status.value" :error="lanes.error.value" :stale="lanes.stale.value" @retry="lanes.reload" />
          <p v-if="lanes.data.value?.strict_unavailable" class="note attn small">
            {{ lanes.data.value.strict_unavailable }} 条指标到达时间未知，当时已知模式下不参与。
          </p>
          <TrendChart
            :lanes="3"
            :axes="[{ lane: 0, name: '社会反应（条）' }, { lane: 1, name: '组织发布（条）' }, { lane: 2, name: '交通影响（列/站）' }]"
            :series="[
              { name: '个人微博', data: personal, color: COLORS.obs, axis: 0, area: true },
              { name: '求助', data: help, color: COLORS.muted, axis: 0, type: 'bar' },
              { name: '官方发布', data: official, color: COLORS.accent, axis: 1, type: 'bar' },
              { name: '受影响车次', data: trains, color: COLORS.attn, axis: 2, type: 'bar' },
              { name: '受影响站点', data: stations, color: COLORS.violet, axis: 2 },
            ]"
            :cursor="ctx.cursor"
            :cursor-label="fmtTime(ctx.cursor, false)"
            :x-min="ctx.event?.start_time"
            :x-max="ctx.event?.end_time"
            :height="420"
            :summary="summary"
            aria-label="社会、组织、物理三条泳道"
            @pick="ctx.setCursor"
          />
          <TimeAxis
            v-if="ctx.event"
            :start="ctx.event.start_time"
            :end="ctx.event.end_time"
            :model-value="ctx.cursor"
            @update:model-value="ctx.setCursor"
          />
        </section>
        <aside class="locator" aria-labelledby="loc-title">
          <h2 id="loc-title">影响定位</h2>
          <p class="muted small">{{ fmtTime(locatorCard?.hour_bj) }} 各省受影响车次</p>
          <ProvinceMap
            :values="locatorCard?.provinces || {}"
            :selected="ctx.province || null"
            label="受影响车次"
            unit="列"
            :height="300"
            compact
            @select="(code) => (ctx.province = code || '')"
          />
          <p class="muted small">点击省份可切换泳道省份；当前：{{ provinceName(ctx.province || 'ALL') }}</p>
        </aside>
      </div>

      <section class="section" aria-labelledby="log-title">
        <div class="section-head">
          <h2 id="log-title">事件记录（共 {{ logItems.length }} 条）</h2>
          <span class="muted small">
            游标前 {{ LOG_BEFORE }} 小时{{ ctx.strict ? '内已获知' : `至游标后 ${LOG_AFTER} 小时` }}的记录，按获知时间排序；“获知”指数据到达平台的时间。
          </span>
        </div>
        <StatusNote
          :status="log.status.value"
          :error="log.error.value"
          :stale="log.stale.value"
          :empty="!logItems.length"
          empty-text="该时间窗内没有可展示的事件记录。"
          @retry="log.reload"
        />
        <div v-if="logItems.length" class="table-wrap log">
          <table class="data">
            <thead>
              <tr>
                <th>发生时间</th>
                <th>获知时间</th>
                <th>类型</th>
                <th>简要描述</th>
                <th>地区</th>
                <th>证据</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="it in logItems" :key="it.ref + it.kind" :class="{ future: afterCursor(it) }">
                <td class="num">{{ fmtTime(it.time) }}</td>
                <td class="num">
                  {{ fmtTime(it.known_at) }}
                  <span v-if="afterCursor(it)" class="tag attn">游标后获知</span>
                </td>
                <td><span class="dot" :style="{ background: KIND[it.kind].color }"></span>{{ KIND[it.kind].label }}</td>
                <td>{{ it.label }}</td>
                <td>{{ it.province_code ? provinceName(it.province_code) : '—' }}</td>
                <td>
                  <button v-if="it.kind === 'anomaly'" type="button" class="btn ghost" @click="openRef(it)">查看证据</button>
                  <span v-else class="muted small">{{ it.ref }}</span>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </ContextGate>
  </div>
</template>

<style scoped>
.mode button {
  min-width: 96px;
}
.replay-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 300px;
  gap: 24px;
}
.locator {
  border-left: 1px solid var(--line);
  padding-left: 20px;
}
.log {
  max-height: 420px;
  overflow-y: auto;
}
tr.future td {
  color: var(--faint);
}
.dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
}
@media (max-width: 1100px) {
  .replay-grid {
    grid-template-columns: 1fr;
  }
  .locator {
    border-left: 0;
    padding-left: 0;
  }
}
</style>
