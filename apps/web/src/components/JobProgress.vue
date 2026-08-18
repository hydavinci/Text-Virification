<script setup lang="ts">
import { computed } from 'vue'

import { isTerminalJobStatus, type JobStatus } from '../types/jobs'

interface JobProgressState {
  sourceName: string
  status: JobStatus
  progress: number
  message: string
  failureMessage: string | null
  connectionMessage: string | null
}

const props = defineProps<{
  state: JobProgressState
}>()

const isTerminal = computed(() => isTerminalJobStatus(props.state.status))
const statusLabel = computed(() => {
  const labels: Record<JobStatus, string> = {
    queued: '等待处理',
    upload_validated: '上传完成',
    parsing: '正在解析',
    checking_format: '格式检查',
    checking_sensitive: '敏感内容检查',
    checking_chinese: '中文检查',
    checking_english: '英文检查',
    completed: '核验完成',
    partial: '部分完成',
    failed: '处理失败',
    expired: '任务已过期'
  }

  return labels[props.state.status]
})
</script>

<template>
  <section class="progress-panel">
    <div class="progress-panel__heading">
      <span>2</span>
      <div>
        <h2>核验进度</h2>
        <p>任务状态将实时更新</p>
      </div>
    </div>

    <div class="progress-panel__file">
      <span class="progress-panel__file-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24">
          <path d="M7 3h7l4 4v14H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2Z" />
          <path d="M14 3v5h5" />
        </svg>
      </span>
      <div>
        <strong>{{ state.sourceName }}</strong>
        <span>源文档</span>
      </div>
      <span class="progress-panel__badge">{{ statusLabel }}</span>
    </div>

    <div class="progress-panel__meta">
      <span>{{ state.message }}</span>
      <strong>{{ state.progress }}%</strong>
    </div>
    <progress aria-label="任务进度" :value="state.progress" max="100">{{ state.progress }}%</progress>
    <p class="sr-only" role="status" aria-live="polite">
      状态代码：{{ state.status }}，进度 {{ state.progress }}%，{{ state.message }}
    </p>
    <p v-if="isTerminal" class="progress-panel__terminal">任务已进入最终状态：{{ statusLabel }}</p>
    <p v-if="state.failureMessage" class="progress-panel__notice progress-panel__notice--error" role="alert">
      {{ state.failureMessage }}
    </p>
    <p
      v-else-if="state.connectionMessage"
      class="progress-panel__notice"
      role="status"
      aria-live="polite"
    >
      {{ state.connectionMessage }}
    </p>
  </section>
</template>

<style scoped>
.progress-panel {
  padding: 30px 34px 34px;
  border-top: 1px solid #edf0f6;
}

.progress-panel__heading {
  display: flex;
  align-items: center;
  gap: 13px;
  margin-bottom: 22px;
}

.progress-panel__heading > span {
  display: grid;
  width: 32px;
  height: 32px;
  place-items: center;
  color: #fff;
  font-size: 0.88rem;
  font-weight: 700;
  background: #5b6ff2;
  border-radius: 10px;
}

h2 {
  margin: 0;
  color: #20283a;
  font-size: 1.1rem;
}

.progress-panel__heading p {
  margin: 4px 0 0;
  color: #667085;
  font-size: 0.82rem;
}

.progress-panel__file {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 15px;
  background: #f7f8fc;
  border-radius: 13px;
}

.progress-panel__file-icon {
  display: grid;
  width: 42px;
  height: 42px;
  flex: 0 0 auto;
  place-items: center;
  color: #6476ec;
  background: #e8ebff;
  border-radius: 10px;
}

.progress-panel__file-icon svg {
  width: 23px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 1.8;
}

.progress-panel__file div {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 3px;
}

.progress-panel__file strong {
  overflow: hidden;
  color: #30394d;
  font-size: 0.9rem;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.progress-panel__file div span {
  color: #667085;
  font-size: 0.75rem;
}

.progress-panel__badge {
  flex: 0 0 auto;
  padding: 6px 10px;
  color: #4e5fce;
  font-size: 0.75rem;
  font-weight: 700;
  background: #e9ecff;
  border-radius: 999px;
}

.progress-panel__meta {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin: 22px 0 9px;
  color: #697287;
  font-size: 0.84rem;
}

.progress-panel__meta strong {
  color: #5568de;
}

progress {
  display: block;
  width: 100%;
  height: 9px;
  overflow: hidden;
  appearance: none;
  background: #e9edf5;
  border: 0;
  border-radius: 999px;
}

progress::-webkit-progress-bar {
  background: #e9edf5;
  border-radius: 999px;
}

progress::-webkit-progress-value {
  background: linear-gradient(90deg, #657af5, #7562e5);
  border-radius: 999px;
}

progress::-moz-progress-bar {
  background: linear-gradient(90deg, #657af5, #7562e5);
  border-radius: 999px;
}

.progress-panel__terminal,
.progress-panel__notice {
  margin: 16px 0 0;
  color: #5e687c;
  font-size: 0.82rem;
}

.progress-panel__notice {
  padding: 11px 13px;
  background: #fff9e8;
  border-radius: 9px;
}

.progress-panel__notice--error {
  color: #a53535;
  background: #fff2f2;
}

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (max-width: 560px) {
  .progress-panel {
    padding: 24px 20px;
  }
}
</style>
