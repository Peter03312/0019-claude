<script setup>
import { reactive, ref, watch } from 'vue'
import ResultView from './components/ResultView.vue'

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

// 试样记录：保存当前裁决
const sampleId = ref('')
const saving = ref(false)
const saveError = ref('')
const saveOk = ref('')

// 试样记录：按编号查询（只读，不触碰当前录入）
const queryId = ref('')
const querying = ref(false)
const queryError = ref('')
const record = ref(null)

// 修改任一读数（或增减行数）立即清除旧裁决与旧的逐字段错误
watch(
  [wetMass, dryMasses],
  () => {
    result.value = null
    topError.value = ''
    fieldErrors.wet_mass = null
    fieldErrors.dry_count = null
    fieldErrors.dry_masses = []
    saveError.value = ''
    saveOk.value = ''
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

// 保存：服务端按同一规则重算当前录入，恒重才入库；重复编号返回冲突提示
async function saveRecord() {
  saving.value = true
  saveError.value = ''
  saveOk.value = ''
  try {
    const resp = await fetch('/api/records', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        sample_id: sampleId.value,
        wet_mass: wetMass.value,
        dry_masses: dryMasses.map((d) => d.value),
      }),
    })
    const body = await resp.json()
    if (resp.ok) {
      saveOk.value = `已保存为试样记录：编号 ${body.sample_id}，保存时间 ${body.saved_at}。之后可在下方按编号查询。`
    } else if (resp.status === 409) {
      saveError.value = body.detail || '该试样编号已存在，请更换编号。'
    } else if (resp.status === 422) {
      saveError.value = body.detail || '输入有误，无法保存。'
    } else {
      saveError.value = `服务异常（HTTP ${resp.status}），保存失败。`
    }
  } catch (err) {
    saveError.value = '无法连接裁决服务，保存失败。'
  } finally {
    saving.value = false
  }
}

// 查询：结果只读展示在查询区，不覆盖当前录入内容
async function queryRecord() {
  const id = queryId.value.trim()
  queryError.value = ''
  record.value = null
  if (!id) {
    queryError.value = '请输入要查询的试样编号。'
    return
  }
  querying.value = true
  try {
    const resp = await fetch(`/api/records/${encodeURIComponent(id)}`)
    const body = await resp.json()
    if (resp.ok) {
      record.value = body
    } else if (resp.status === 404) {
      queryError.value = body.detail || `未找到试样编号 ${id} 的记录。`
    } else {
      queryError.value = `服务异常（HTTP ${resp.status}），查询失败。`
    }
  } catch (err) {
    queryError.value = '无法连接裁决服务，查询失败。'
  } finally {
    querying.value = false
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
        已恒重的裁决可填写试样编号保存为记录，之后按编号只读查询。
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
      <ResultView :result="result" title="裁决结果" />

      <!-- 保存为试样记录：尚未恒重时禁用 -->
      <div class="save-area">
        <label class="field-label" for="sample-id">
          试样编号
          <span class="hint">
            {{ result.constant ? '保存后不可改写，可按编号查询' : '尚未恒重，不能保存为试样记录' }}
          </span>
        </label>
        <div class="save-row">
          <input
            id="sample-id"
            v-model="sampleId"
            class="mass-input"
            :disabled="!result.constant"
            placeholder="例如 CF-2026-0001"
          />
          <button
            type="button"
            class="btn-primary"
            :disabled="!result.constant || saving"
            @click="saveRecord"
          >
            {{ saving ? '保存中…' : '保存为试样记录' }}
          </button>
        </div>
        <div v-if="saveError" class="field-error">{{ saveError }}</div>
        <div v-if="saveOk" class="save-ok">{{ saveOk }}</div>
      </div>
    </section>

    <section class="card">
      <h2>试样记录查询</h2>
      <div class="save-row">
        <input
          id="query-id"
          v-model="queryId"
          class="mass-input"
          placeholder="输入试样编号，例如 CF-2026-0001"
          @keyup.enter="queryRecord"
        />
        <button type="button" class="btn-primary" :disabled="querying" @click="queryRecord">
          {{ querying ? '查询中…' : '查询' }}
        </button>
      </div>
      <div v-if="queryError" class="field-error">{{ queryError }}</div>

      <!-- 查询结果只读展示，不影响上方录入与裁决 -->
      <div v-if="record" class="record-view">
        <div class="record-meta">
          <div>试样编号：<strong>{{ record.sample_id }}</strong></div>
          <div>保存时间：{{ record.saved_at }}</div>
          <div>烘前湿样质量：<strong>{{ record.wet_mass }} g</strong></div>
          <div>
            烘后序列（共 {{ record.dry_masses.length }} 次）：
            <span v-for="(mass, i) in record.dry_masses" :key="i">
              第 {{ i + 1 }} 次 <strong>{{ mass }} g</strong>{{ i < record.dry_masses.length - 1 ? '，' : '' }}
            </span>
          </div>
        </div>
        <ResultView :result="record" title="试样记录（只读）" />
      </div>
    </section>
  </div>
</template>
