<script setup>
// 裁决/记录共用的只读结果展示：轮次表、首次恒重对、回潮率算式与结论
defineProps({
  result: { type: Object, required: true },
  title: { type: String, default: '裁决结果' },
})
</script>

<template>
  <h2>
    {{ title }}
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
</template>
