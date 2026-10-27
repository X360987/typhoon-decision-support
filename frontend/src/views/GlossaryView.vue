<script setup lang="ts">
import { computed } from 'vue'
import { api } from '../api/client'
import StatusNote from '../components/StatusNote.vue'
import { useLoader } from '../composables/useLoader'
import { dimensionNames, fmtTime, provinceName } from '../lib/format'
import { useContextStore } from '../stores/context'

const ctx = useContextStore()

const registry = useLoader((signal) => api.registry(signal), () => ctx.revision)
const models = useLoader((signal) => api.models(signal), () => ctx.revision)

const RULE_LABELS: Record<string, string> = {
  'single.window_hours': '单维基线窗口（小时）',
  'single.min_samples': '单维最少样本数',
  'single.mad_z_threshold': '稳健 Z 分数阈值（MAD）',
  'single.quantile_threshold': '分位数阈值',
  'single.consecutive_hours': '持续小时数',
  'single.social.negative_ratio_abs_floor': '负面比例绝对下限',
  'single.social.discussion_spike_factor': '讨论量突增倍数',
  'single.org.publish_drop_factor': '官方发布骤降比例',
  'single.org.publish_spike_factor': '官方发布突增倍数',
  'single.org.gap_hours': '官方发布空窗（小时，按实际时间）',
  'single.physical.suspension_spike_factor': '停运突增倍数',
  'single.physical.affected_trains_abs_floor': '受影响车次绝对下限',
  'pair.lag_hours': '两维滞后窗口（小时）',
  'pair.min_coverage': '两维最低覆盖率',
  'pair.relation_z_threshold': '关系偏离 Z 阈值',
  'pair.social_org.discussion_vs_official_imbalance': '讨论/官方发布失衡倍数',
  'pair.social_physical.emotion_vs_suspension_imbalance': '情绪/停运失衡倍数',
  'pair.org_physical.official_vs_suspension_lag_hours': '官方发布滞后停运（小时）',
  'joint.min_dimensions_with_signal': '三维同步所需信号维度数',
  'joint.lag_hours': '三维对齐窗口（小时）',
  'joint.score_threshold': '三维综合分阈值',
  'joint.imbalance_enabled': '输出三维关系失衡',
  'accounts.unverified_default': '未核验账号默认归类',
  'replay.strict_requires_available_at': '当时已知回放要求到达时间',
}

function flatten(prefix: string, value: unknown, out: Array<{ key: string; value: string }>) {
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    for (const [k, v] of Object.entries(value)) flatten(prefix ? `${prefix}.${k}` : k, v, out)
  } else {
    out.push({ key: prefix, value: Array.isArray(value) ? value.join(', ') : String(value) })
  }
}

const ruleRows = computed(() => {
  const out: Array<{ key: string; value: string }> = []
  flatten('', registry.data.value?.rules || {}, out)
  return out
})

const anomalyCsv = computed(() => api.exportUrl('anomalies', ctx.params))
const metricCsv = computed(() => api.exportUrl('metrics', ctx.params))
</script>

<template>
  <div class="page">
    <div class="page-head">
      <RouterLink class="small" to="/data">‹ 数据管理</RouterLink>
      <h1>资料与口径</h1>
      <span class="muted small">规则版本 {{ registry.data.value?.rule_version ?? '—' }} · 数据版本 {{ ctx.dataVersion || ctx.event?.active_version || '—' }} · 时区 北京时间（Asia/Shanghai）</span>
    </div>

    <section class="section" aria-labelledby="exp-title">
      <div class="section-head"><h2 id="exp-title">导出与复现</h2></div>
      <p class="small">
        导出的 CSV 每行都带数据集、事件、数据版本、规则版本、回放模式、截止时刻和时区，可据此复现页面结果。当前上下文：
        {{ ctx.event?.name || '未选择事件' }} · {{ ctx.province ? provinceName(ctx.province) : '全部省份' }} ·
        {{ ctx.replayMode === 'as_known' ? `当时已知（截至 ${fmtTime(ctx.cursor)}）` : '事后复盘' }}
      </p>
      <div v-if="ctx.ready" class="links">
        <a class="btn" :href="anomalyCsv" download>导出异常 CSV</a>
        <a class="btn" :href="metricCsv" download>导出指标 CSV</a>
      </div>
      <p v-else class="muted small">选择事件后可导出。</p>
    </section>

    <section class="section" aria-labelledby="metric-title">
      <div class="section-head"><h2 id="metric-title">指标口径</h2></div>
      <StatusNote :status="registry.status.value" :error="registry.error.value" @retry="registry.reload" />
      <div v-if="registry.data.value" class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>指标</th>
              <th>维度</th>
              <th>单位</th>
              <th>分子 / 分母</th>
              <th>去重键</th>
              <th>全国口径</th>
              <th>版本</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in registry.data.value.items" :key="m.id">
              <td>
                <strong>{{ m.name }}</strong>
                <div class="muted small">{{ m.id }}<template v-if="m.description"> · {{ m.description }}</template></div>
              </td>
              <td>{{ dimensionNames([m.dimension]) }}</td>
              <td>{{ m.unit || '—' }}</td>
              <td>{{ m.numerator ? `${m.numerator}${m.denominator ? ` / ${m.denominator}` : ''}` : '—' }}</td>
              <td>{{ m.dedup_key || '—' }}</td>
              <td>{{ m.national_rule || m.aggregation || '—' }}</td>
              <td>{{ m.version }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="section" aria-labelledby="rule-title">
      <div class="section-head"><h2 id="rule-title">异常判定阈值</h2></div>
      <div v-if="ruleRows.length" class="table-wrap narrow">
        <table class="data">
          <thead>
            <tr>
              <th>参数</th>
              <th>取值</th>
              <th>配置键</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="r in ruleRows" :key="r.key">
              <td>{{ RULE_LABELS[r.key] || r.key }}</td>
              <td class="num">{{ r.value }}</td>
              <td class="muted small">{{ r.key }}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>

    <section class="section" aria-labelledby="model-title">
      <div class="section-head"><h2 id="model-title">预测模型</h2></div>
      <StatusNote :status="models.status.value" :error="models.error.value" :empty="!models.data.value?.items.length" empty-text="尚未训练模型；预测页只显示基线方法。" @retry="models.reload" />
      <div v-if="models.data.value?.items.length" class="table-wrap">
        <table class="data">
          <thead>
            <tr>
              <th>模型</th>
              <th>目标 / 提前量</th>
              <th>数据模式</th>
              <th>特征契约</th>
              <th>训练窗口</th>
              <th>评估</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="m in models.data.value.items" :key="m.model_key">
              <td>
                {{ m.model_kind }}
                <div class="muted small">{{ m.version }}</div>
              </td>
              <td>{{ m.target_id }} · {{ m.horizon_hours }}h</td>
              <td><span class="tag" :class="m.data_mode === 'real' ? 'real' : 'demo'">{{ m.data_mode === 'real' ? '真实' : '模拟' }}</span></td>
              <td class="small">
                <template v-if="m.feature_contract">{{ m.feature_contract.version }}：{{ m.feature_contract.names.join('、') }}（缺失处理：{{ m.feature_contract.missing }}）</template>
                <template v-else>—</template>
              </td>
              <td class="small">
                <template v-if="m.train_window">
                  <div v-for="(v, k) in m.train_window" :key="k">{{ k }}：{{ v }}</div>
                </template>
                <template v-else>—</template>
              </td>
              <td class="small">
                <template v-if="m.metrics">
                  <div v-for="(v, k) in m.metrics" :key="k">{{ k }}：{{ v ?? '—' }}</div>
                </template>
                <template v-else>—</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      <p class="small muted">模型只在单一事件的模拟数据上训练，未经跨事件验证；区间需要足够的历史残差，样本不足时不显示区间。</p>
    </section>

    <section class="section" aria-labelledby="bound-title">
      <div class="section-head"><h2 id="bound-title">证据边界</h2></div>
      <ul class="bounds">
        <li>异常是统计偏离提示，需要人工核验；平台不自动发布、不派发任务、不认定责任。</li>
        <li>“当时已知”回放只使用到达时间（available_at）不晚于游标的数据；物理指标以通告所在小时为可用时刻，社会指标在该小时结束后可用。</li>
        <li>缺测小时显示为缺测，不按 0 计算；“全国”为跨省去重结果，不是各省相加。</li>
        <li>未核验且认证类型无法判定的账号归为“未知身份”，不计入个人或官方。</li>
        <li>停运区段无法匹配到站点时进入待核验，不推断影响省份；恢复数据未接入时不显示恢复进度。</li>
        <li>模拟数据全部带“模拟”标注，真实模式下不会用模拟数据填充空状态。</li>
        <li>原始微博内容在证据面板中脱敏显示，用户标识只保留部分字符。</li>
      </ul>
    </section>
  </div>
</template>

<style scoped>
.links {
  display: flex;
  gap: 10px;
  margin-top: 8px;
}
.links .btn {
  text-decoration: none;
}
.narrow {
  max-width: 820px;
}
.bounds {
  padding-left: 18px;
  line-height: 1.8;
  color: #334155;
}
</style>
