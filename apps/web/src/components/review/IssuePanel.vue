<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type { Issue } from '../../types/analysis'
import type { DecisionAction } from '../../types/review'
import { categoryLabel, issueTypeLabel } from './presentation'
import { describeSeverity } from './severity'

type ReviewDecisionAction = DecisionAction | 'custom'

const props = defineProps<{
  issue: Issue | null
  decisionError: string | null
  canRetryDecision: boolean
}>()

const emit = defineEmits<{
  decide: [action: ReviewDecisionAction, replacement?: string]
  retryDecision: []
}>()

const customReplacement = ref('')
const customReplacementError = ref<string | null>(null)
const decisionLabel = computed(() => {
  switch (props.issue?.decision?.action) {
    case 'accepted':
      return '已接受'
    case 'ignored':
      return '已忽略'
    case 'custom':
      return '已自定义'
    default:
      return '未处理'
  }
})
const severityLabel = computed(() => {
  if (!props.issue) {
    return null
  }

  const presentation = describeSeverity(props.issue.severity)
  return `${presentation.icon} ${presentation.text}`
})

watch(
  () => props.issue,
  (issue) => {
    customReplacement.value =
      issue?.decision?.action === 'accepted' || issue?.decision?.action === 'custom'
        ? issue.decision.replacement ?? ''
        : ''
    customReplacementError.value = null
  },
  { immediate: true }
)

function submitDecision(action: Extract<DecisionAction, 'accepted' | 'ignored'>): void {
  customReplacementError.value = null
  emit('decide', action)
}

function submitCustomDecision(): void {
  const error = validateCustomReplacement(customReplacement.value)
  customReplacementError.value = error
  if (error) {
    return
  }
  emit('decide', 'custom', customReplacement.value)
}

function validateCustomReplacement(replacement: string): string | null {
  if (!replacement.trim()) {
    return '请输入自定义替换内容。'
  }
  if (replacement.includes('\u0000')) {
    return '自定义替换不能包含 NUL 字符。'
  }
  if (Array.from(replacement).length > 10_000) {
    return '自定义替换不能超过 10,000 个 Unicode 字符。'
  }
  return null
}
</script>

<template>
  <aside class="issue-panel" aria-label="问题详情">
    <template v-if="issue">
      <div class="issue-panel__heading">
        <div>
          <p class="issue-panel__type">{{ issueTypeLabel(issue.type) }}</p>
          <h2>{{ issue.message }}</h2>
        </div>
        <span
          class="issue-panel__severity"
          :class="`issue-panel__severity--${issue.severity}`"
        >
          {{ severityLabel }}
        </span>
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
          <dt>检查类别</dt>
          <dd>{{ categoryLabel(issue.layer) }}</dd>
        </div>
        <div>
          <dt>上下文</dt>
          <dd>{{ issue.context }}</dd>
        </div>
      </dl>

      <section class="issue-panel__decisions" aria-label="问题处理">
        <div class="issue-panel__decision-heading">
          <h3>处理决定</h3>
          <span>{{ decisionLabel }}</span>
        </div>
        <div class="issue-panel__decision-buttons">
          <button type="button" name="accept" @click="submitDecision('accepted')">
            接受建议
          </button>
          <button type="button" name="ignore" @click="submitDecision('ignored')">
            忽略问题
          </button>
        </div>
        <label>
          <span>自定义替换</span>
          <textarea
            v-model="customReplacement"
            aria-label="自定义替换"
            rows="4"
            @input="customReplacementError = null"
          />
        </label>
        <button
          type="button"
          name="custom-decision"
          class="issue-panel__custom-button"
          @click="submitCustomDecision"
        >
          保存自定义替换
        </button>
        <p
          v-if="customReplacementError"
          class="issue-panel__validation-error"
          data-testid="custom-replacement-error"
          role="alert"
        >
          {{ customReplacementError }}
        </p>
        <div
          v-if="decisionError"
          class="issue-panel__decision-error"
          data-testid="decision-error"
          role="alert"
        >
          <p>{{ decisionError }}</p>
          <button
            v-if="canRetryDecision"
            type="button"
            data-testid="retry-decision"
            @click="emit('retryDecision')"
          >
            重试保存
          </button>
        </div>
      </section>
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
}

.issue-panel__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--review-space-3);
  padding-bottom: var(--review-space-4);
  border-bottom: 1px solid var(--review-border);
}

.issue-panel__heading p {
  margin: 0 0 5px;
  color: var(--review-accent);
  font-size: 0.72rem;
  font-weight: 800;
  text-transform: uppercase;
  white-space: nowrap;
}

h2 {
  margin: 0;
  color: var(--review-text);
  font-size: 1rem;
  line-height: 1.45;
}

.issue-panel__heading > span {
  padding: 5px 8px;
  font-size: 0.68rem;
  font-weight: 800;
  border-radius: 999px;
  text-transform: uppercase;
  white-space: nowrap;
}

.issue-panel__severity--error {
  color: #b42318;
  background: #fee4e2;
}

.issue-panel__severity--warning {
  color: #9a4a21;
  background: #fff0e6;
}

.issue-panel__severity--info {
  color: #175cd3;
  background: #d1e9ff;
}

dl {
  display: grid;
  gap: var(--review-space-4);
  margin: calc(var(--review-space-4) + 2px) 0 0;
}

dl div {
  display: grid;
  gap: 6px;
}

dt {
  color: var(--review-text-muted);
  font-size: 0.72rem;
  font-weight: 700;
}

dd {
  margin: 0;
  color: var(--review-text);
  font-size: 0.86rem;
  line-height: 1.6;
  overflow-wrap: anywhere;
}

.issue-panel__empty {
  display: grid;
  min-height: 220px;
  place-content: center;
  color: var(--review-text-muted);
  text-align: center;
}

.issue-panel__empty strong {
  color: var(--review-text);
}

.issue-panel__empty p {
  max-width: 220px;
  margin: 8px 0 0;
  font-size: 0.8rem;
  line-height: 1.55;
}

.issue-panel__decisions {
  display: grid;
  gap: var(--review-space-3);
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--review-border);
}

.issue-panel__decision-heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: calc(var(--review-space-2) + 2px);
}

.issue-panel__decision-heading h3 {
  margin: 0;
  color: var(--review-text);
  font-size: 0.86rem;
}

.issue-panel__decision-heading span {
  color: var(--review-accent);
  font-size: 0.72rem;
  font-weight: 800;
  white-space: nowrap;
}

.issue-panel__decision-buttons {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--review-space-2);
}

.issue-panel__decisions button {
  min-height: 44px;
  padding: 9px 10px;
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 0;
  border-radius: calc(var(--review-panel-radius) - 4px);
  cursor: pointer;
}

.issue-panel__decision-buttons button:last-child {
  color: var(--review-text-muted);
  background: var(--review-surface);
  border: 1px solid var(--review-border);
}

.issue-panel__decisions label {
  display: grid;
  gap: 6px;
  color: var(--review-text-muted);
  font-size: 0.72rem;
  font-weight: 700;
}

.issue-panel__decisions textarea {
  width: 100%;
  min-height: 44px;
  padding: 9px;
  color: var(--review-text);
  font: inherit;
  line-height: 1.5;
  resize: vertical;
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.issue-panel__custom-button {
  justify-self: start;
}

.issue-panel__decisions button:focus-visible,
.issue-panel__decisions textarea:focus-visible {
  outline: 3px solid #8ea2ff;
  outline-offset: 2px;
}

.issue-panel__validation-error,
.issue-panel__decision-error {
  margin: 0;
  color: var(--review-danger);
  font-size: 0.78rem;
  line-height: 1.45;
}

.issue-panel__decision-error {
  padding: 11px;
  background: #fff2f2;
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.issue-panel__decision-error p {
  margin: 0 0 9px;
}
</style>
