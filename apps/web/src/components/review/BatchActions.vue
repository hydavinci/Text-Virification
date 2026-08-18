<script setup lang="ts">
import { computed } from 'vue'

const props = defineProps<{
  issueCount: number
  batchLimit: number
  highRiskSecurityCount: number
  busy: boolean
  error: string | null
}>()

const emit = defineEmits<{
  acceptVisible: []
  ignoreVisible: []
}>()

const scopedIssueCount = computed(() => Math.min(props.issueCount, props.batchLimit))
const hasIssues = computed(() => scopedIssueCount.value > 0)
const hasOverflow = computed(() => props.issueCount > props.batchLimit)

function requestAcceptVisible(): void {
  if (props.highRiskSecurityCount > 0) {
    const confirmed =
      globalThis.confirm?.(
        `当前包含 ${props.highRiskSecurityCount} 个高风险安全问题，确认批量接受建议吗？`
      ) ?? true

    if (!confirmed) {
      return
    }
  }

  emit('acceptVisible')
}
</script>

<template>
  <section class="batch-actions" aria-label="批量处理">
    <div class="batch-actions__heading">
      <div>
        <strong>批量处理当前筛选结果</strong>
        <p>仅处理当前已加载的问题，最多 {{ batchLimit }} 项。</p>
      </div>
      <span>{{ scopedIssueCount }} 项</span>
    </div>

    <p v-if="hasOverflow" class="batch-actions__notice">
      当前仅批量处理前 {{ batchLimit }} 项
    </p>

    <div class="batch-actions__buttons">
      <button
        type="button"
        name="accept-visible"
        :disabled="busy || !hasIssues"
        @click="requestAcceptVisible"
      >
        接受当前页
      </button>
      <button
        type="button"
        name="ignore-visible"
        :disabled="busy || !hasIssues"
        @click="emit('ignoreVisible')"
      >
        忽略当前页
      </button>
    </div>

    <p v-if="error" class="batch-actions__error" role="alert">{{ error }}</p>
  </section>
</template>

<style scoped>
.batch-actions {
  display: grid;
  gap: 10px;
  padding: 14px 16px;
  background: #f8f9ff;
  border: 1px solid #dfe4f4;
  border-radius: 14px;
}

.batch-actions__heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.batch-actions__heading strong {
  display: block;
  color: #243154;
  font-size: 0.86rem;
}

.batch-actions__heading p,
.batch-actions__notice,
.batch-actions__error {
  margin: 4px 0 0;
  font-size: 0.76rem;
  line-height: 1.5;
}

.batch-actions__heading p,
.batch-actions__notice {
  color: #667085;
}

.batch-actions__heading > span {
  padding: 4px 8px;
  color: #4356c9;
  font-size: 0.74rem;
  font-weight: 800;
  background: #eef0ff;
  border-radius: 999px;
}

.batch-actions__buttons {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

.batch-actions__buttons button {
  padding: 9px 11px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 1px solid transparent;
  border-radius: 9px;
  cursor: pointer;
}

.batch-actions__buttons button:last-child {
  color: #596276;
  background: #f0f2f6;
}

.batch-actions__buttons button:focus-visible {
  outline: 2px solid #6579e8;
  outline-offset: 2px;
}

.batch-actions__buttons button:disabled {
  color: #8c93a8;
  cursor: not-allowed;
  background: #f2f4f8;
}

.batch-actions__error {
  margin: 0;
  color: #a53636;
}
</style>
