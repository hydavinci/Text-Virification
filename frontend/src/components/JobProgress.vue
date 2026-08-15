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
        <dt>Progress</dt>
        <dd>{{ state.progress }}%</dd>
      </div>
    </dl>
    <progress :value="state.progress" max="100">{{ state.progress }}%</progress>
    <p>Current message: {{ state.message }}</p>
    <p v-if="isTerminal">Terminal state retained: {{ state.status }}</p>
    <p v-if="state.failureMessage">{{ state.failureMessage }}</p>
    <p v-else-if="state.connectionMessage">{{ state.connectionMessage }}</p>
  </section>
</template>
