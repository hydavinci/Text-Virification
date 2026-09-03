<script setup lang="ts">
import { computed } from 'vue'

import {
  isTerminalJobStatus,
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

const props = defineProps<{
  state: JobProgressState
}>()

const isTerminal = computed(() => isTerminalJobStatus(props.state.status))
</script>

<template>
  <section>
    <h2>Job progress</h2>
    <dl>
      <div>
        <dt>Source</dt>
        <dd>{{ state.sourceName }}</dd>
      </div>
      <div>
        <dt>Status</dt>
        <dd>{{ state.status }}</dd>
      </div>
      <div>
        <dt>Stage</dt>
        <dd data-job-stage>{{ state.stage }}</dd>
      </div>
      <div>
        <dt>Progress</dt>
        <dd>{{ state.progress }}%</dd>
      </div>
    </dl>
    <progress aria-label="Job progress" :value="state.progress" max="100">{{ state.progress }}%</progress>
    <p role="status" aria-live="polite">
      Status: {{ state.status }} · {{ state.progress }}% · {{ state.message }}
    </p>
    <p v-if="isTerminal">Terminal state retained: {{ state.status }}</p>
    <p v-if="state.failureMessage" role="alert">{{ state.failureMessage }}</p>
    <p v-else-if="state.connectionMessage" role="status" aria-live="polite">
      {{ state.connectionMessage }}
    </p>
  </section>
</template>
