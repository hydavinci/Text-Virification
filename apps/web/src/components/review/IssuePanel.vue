<script setup lang="ts">
import type { Issue } from '../../types/analysis'

defineProps<{
  issue: Issue | null
}>()
</script>

<template>
  <aside class="issue-panel" aria-label="问题详情">
    <template v-if="issue">
      <div class="issue-panel__heading">
        <div>
          <p>{{ issue.type }}</p>
          <h2>{{ issue.message }}</h2>
        </div>
        <span>{{ issue.severity }}</span>
      </div>

      <dl>
        <div>
          <dt>原文</dt>
          <dd>{{ issue.original }}</dd>
        </div>
        <div>
          <dt>建议</dt>
          <dd>{{ issue.suggestion ?? '暂无替换建议' }}</dd>
        </div>
        <div>
          <dt>规则</dt>
          <dd>{{ issue.rule_id }}</dd>
        </div>
        <div>
          <dt>上下文</dt>
          <dd>{{ issue.context }}</dd>
        </div>
      </dl>
    </template>

    <div v-else class="issue-panel__empty">
      <strong>请选择问题</strong>
      <p>从左侧问题列表或文档高亮中选择一项查看详情。</p>
    </div>
  </aside>
</template>

<style scoped>
.issue-panel {
  min-width: 0;
  overflow: auto;
  padding: 18px;
  background: #fff;
  border: 1px solid #e2e7f0;
  border-radius: 16px;
}

.issue-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding-bottom: 16px;
  border-bottom: 1px solid #edf0f5;
}

.issue-panel__heading p {
  margin: 0 0 5px;
  color: #6575d7;
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
}

h2 {
  margin: 0;
  color: #20283a;
  font-size: 1rem;
  line-height: 1.45;
}

.issue-panel__heading > span {
  padding: 5px 8px;
  color: #9a4a21;
  font-size: 0.68rem;
  font-weight: 800;
  background: #fff0e6;
  border-radius: 999px;
  text-transform: uppercase;
}

dl {
  display: grid;
  gap: 16px;
  margin: 18px 0 0;
}

dl div {
  display: grid;
  gap: 6px;
}

dt {
  color: #667085;
  font-size: 0.72rem;
  font-weight: 700;
}

dd {
  margin: 0;
  color: #30394d;
  font-size: 0.86rem;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.issue-panel__empty {
  display: grid;
  min-height: 220px;
  place-content: center;
  color: #667085;
  text-align: center;
}

.issue-panel__empty strong {
  color: #30394d;
}

.issue-panel__empty p {
  max-width: 220px;
  margin: 8px 0 0;
  font-size: 0.8rem;
  line-height: 1.55;
}
</style>
