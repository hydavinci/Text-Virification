<script setup lang="ts">
import {
  type JobProgressStage,
  type JobStatus
} from '../types/jobs'

interface JobProgressState {
  sourceName: string
  status: JobStatus
  stage: JobProgressStage
  progress: number
  message: string
  failureMessage: string | null
  connectionMessage: string | null
}

defineProps<{
  state: JobProgressState | null
}>()
</script>

<template>
  <div class="check-progress" data-check-progress>
    <progress
      aria-label="检查进度"
      :aria-valuetext="state ? `${state.progress}% · ${state.message}` : '正在检查，请稍候'"
      :value="state?.progress"
      max="100"
    >{{ state ? `${state.progress}%` : '正在检查' }}</progress>
    <p v-if="state?.failureMessage" class="failure" role="alert">{{ state.failureMessage }}</p>
    <p v-else-if="state?.connectionMessage" role="status" aria-live="polite">
      {{ state.connectionMessage }}
    </p>
  </div>
</template>

<style scoped>
.check-progress { margin-top: 14px; }
progress {
  display: block;
  width: 100%;
  height: 6px;
  border: 0;
  border-radius: 999px;
  overflow: hidden;
  accent-color: var(--primary);
}
p { margin: 8px 0 0; color: var(--muted); font-size: 12px; line-height: 1.6; }
.failure { color: var(--danger); }
</style>
