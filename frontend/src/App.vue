<script setup>
import { reactive, ref, watch } from 'vue'

const MIN_READINGS = 3
const MAX_READINGS = 8

const wetMass = ref('')
const dryMasses = reactive([{ value: '' }, { value: '' }, { value: '' }])

const result = ref(null)
const loading = ref(false)
const topError = ref('')
const fieldErrors = reactive({
  wet_mass: null,
  dry_count: null,
  dry_masses: [],
})

// 修改任一读数（或增减行数）立即清除旧裁决与旧的逐字段错误
watch(
  [wetMass, dryMasses],
  () => {
    result.value = null
    topError.value = ''
    fieldErrors.wet_mass = null
    fieldErrors.dry_count = null
    fieldErrors.dry_masses = []
  },
  { deep: true }
)

function addReading() {
  if (dryMasses.length < MAX_READINGS) dryMasses.push({ value: '' })
}

function removeReading(index) {
  if (dryMasses.length > MIN_READINGS) dryMasses.splice(index, 1)
}

function dryError(index) {
  return fieldErrors.dry_masses[index] || null
}

async function submit() {
  loading.value = true
  topError.value = ''
  try {
    const resp = await fetch('/api/judge', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wet_mass: wetMass.value,
        dry_masses: dryMasses.map((d) => d.value),
      }),
    })
    const body = await resp.json()
    if (resp.ok) {
      result.value = body
      fieldErrors.wet_mass = null
      fieldErrors.dry_count = null
      fieldErrors.dry_masses = []
    } else if (resp.status === 422) {
      result.value = null
      const errors = body.errors || {}
      fieldErrors.wet_mass = errors.wet_mass || null
      fieldErrors.dry_count = errors.dry_count || null
      fieldErrors.dry_masses = errors.dry_masses || []
      topError.value = body.detail || '输入有误，请逐项检查。'
    } else {
      topError.value = `服务异常（HTTP ${resp.status}），请稍后重试。`
    }
  } catch (err) {
    topError.value = '无法连接裁决服务，请确认 API 已启动。'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="container">
    <header>
      <h1>棉纤维烘干恒重与回潮率裁决</h1>
      <p>
        录入烘前湿样质量与按先后顺序取得的 3–8 次烘后质量（克，最多三位小数）。
        系统按“(前次−后次) ÷ 前次 ≤ 0.0005”寻找<strong>首次恒重</strong>，
        以未舍入回潮率裁决闭区间 7.5%–8.5% 是否合格。
      </p>
    </header>

    <div v-if="topError" class="top-error">{{ topError }}</div>

    <section class="card">
      <h2>质量录入</h2>

      <div style="max-width: 320px">
        <label class="field-label" for="wet">
          烘前湿样质量
          <span class="hint">克，必须大于每次烘后质量</span>
        </label>
        <input
          id="wet"
          v-model="wetMass"
          class="mass-input"
          :class="{ invalid: fieldErrors.wet_mass }"
          inputmode="decimal"
          placeholder="例如 8.640"
        />
        <div v-if="fieldErrors.wet_mass" class="field-error">
          {{ fieldErrors.wet_mass }}
        </div>
      </div>
    </section>

    <section class="card">
      <div class="readings-head">
        <h2 style="border: none; padding: 0; margin: 0">烘后质量（按称量先后）</h2>
        <span class="count">已录 {{ dryMasses.length }} / {{ MAX_READINGS }} 次（至少 {{ MIN_READINGS }} 次）</span>
      </div>
      <div v-if="fieldErrors.dry_count" class="field-error" style="margin-bottom: 8px">
        {{ fieldErrors.dry_count }}
      </div>

      <div
        v-for="(item, index) in dryMasses"
        :key="index"
        class="reading-row"
      >
        <div class="reading-index">
          第 {{ index + 1 }} 次
          <span v-if="index > 0" class="round-tag">第 {{ index }} 轮后次</span>
        </div>
        <div>
          <input
            v-model="item.value"
            class="mass-input"
            :class="{ invalid: dryError(index) }"
            inputmode="decimal"
            :placeholder="`第 ${index + 1} 次烘后读数，例如 8.000`"
          />
          <div v-if="dryError(index)" class="field-error">{{ dryError(index) }}</div>
        </div>
        <button
          type="button"
          class="icon-btn"
          title="删除该次读数"
          :disabled="dryMasses.length <= MIN_READINGS"
          @click="removeReading(index)"
        >
          ✕
        </button>
      </div>

      <div class="actions">
        <button
          type="button"
          class="btn-ghost"
          :disabled="dryMasses.length >= MAX_READINGS"
          @click="addReading"
        >
          ＋ 增加一次读数
        </button>
        <button type="button" class="btn-primary" :disabled="loading" @click="submit">
          {{ loading ? '裁决中…' : '开始裁决' }}
        </button>
      </div>
    </section>

    <section v-if="result" class="card">
      <h2>
        裁决结果
        <span
          class="badge"
          :class="result.constant ? '' : 'pending'"
        >
          {{ result.constant ? `第 ${result.hit_round} 轮首次恒重` : '尚未恒重' }}
        </span>
      </h2>

      <table class="rounds">
        <thead>
          <tr>
            <th>轮次</th>
            <th>前次（第 i 次）g</th>
            <th>后次（第 i+1 次）g</th>
            <th>前次−后次 g</th>
            <th>(前−后)÷前</th>
            <th>与 0.0005 比较</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in result.rounds"
            :key="row.round"
            :class="{
              'hit-row': row.status === 'hit',
              'ignored-row': row.status === 'ignored',
            }"
          >
            <td>
              第 {{ row.round }} 轮
              <div class="status-tag" :class="row.status">
                <template v-if="row.status === 'hit'">★ 首次恒重对</template>
                <template v-else-if="row.status === 'ignored'">终点之后·仅展示</template>
                <template v-else>未达恒重</template>
              </div>
            </td>
            <td>{{ row.prev_mass }}</td>
            <td>{{ row.curr_mass }}</td>
            <td>{{ row.loss }}</td>
            <td>{{ row.ratio_display }}</td>
            <td>
              <template v-if="row.status === 'ignored'">不改变终点</template>
              <template v-else-if="row.status === 'hit'">≤ 0.0005，命中</template>
              <template v-else>&gt; 0.0005，继续</template>
            </td>
          </tr>
        </tbody>
      </table>

      <!-- 恒重：突出首次恒重对、完整算式与唯一结论 -->
      <div v-if="result.constant" class="verdict" :class="result.qualified ? 'pass' : 'fail'">
        <div>
          首次恒重对：
          <span class="hit-pair">
            第 {{ result.hit_round }} 次 {{ result.rounds[result.hit_round - 1].prev_mass }} g
            → 第 {{ result.hit_round + 1 }} 次 {{ result.endpoint_mass }} g
          </span>
        </div>
        <div class="endpoint-note">
          恒重终点取后次质量＝第 {{ result.endpoint_index }} 次读数
          <strong>{{ result.endpoint_mass }} g</strong>；其后读数仅展示，不改变终点。
        </div>

        <div class="formula">
          回潮率 ＝ (湿样质量 − 恒重质量) ÷ 恒重质量 × 100<br />
          ＝ {{ result.formula }}
        </div>

        <div class="regain-value">
          回潮率（两位小数）：<strong>{{ result.regain }}%</strong>
          ｜ 合格区间：[7.50%, 8.50%]
        </div>
        <div class="conclusion">结论：{{ result.conclusion }}</div>
      </div>

      <!-- 未恒重：不得显示回潮率 -->
      <div v-else class="verdict pending">
        <div class="conclusion">结论：尚未恒重</div>
        <div>
          全部 {{ result.rounds.length }} 个相邻轮次的 (前次−后次)÷前次 均大于 0.0005，
          未出现首次恒重，<strong>不计算、不显示回潮率</strong>。请继续烘干并称量后再行裁决。
        </div>
      </div>
    </section>
  </div>
</template>
