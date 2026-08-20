<script setup lang="ts">
import { computed } from 'vue'

import type { CheckerFailureMap } from '../../types/analysis'
import { categoryLabel } from './presentation'

const props = defineProps<{
  failures: CheckerFailureMap
}>()

const visibleFailures = computed(() =>
  Object.entries(props.failures).flatMap(([category, failure]) =>
    failure ? [{ category, failure }] : []
  )
)
</script>

<template>
  <section
    v-if="visibleFailures.length"
    class="checker-failures"
    aria-label="未完成的检查类别"
  >
    <strong>部分检查未完成</strong>
    <ul>
      <li v-for="{ category, failure } in visibleFailures" :key="category">
        <span class="checker-failures__category">{{ categoryLabel(category) }}</span>
        <span>{{ failure.message }}</span>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.checker-failures {
  display: grid;
  gap: calc(var(--review-space-2) + 2px);
  padding: var(--review-space-3) calc(var(--review-space-3) + 2px);
  color: #7c3f16;
  background: #fff6e8;
  border: 1px solid #f3d6ad;
  border-radius: var(--review-panel-radius);
}

.checker-failures strong {
  font-size: 0.84rem;
}

.checker-failures ul {
  display: grid;
  gap: var(--review-space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}

.checker-failures li {
  display: flex;
  flex-wrap: wrap;
  gap: calc(var(--review-space-2) - 1px);
  font-size: 0.8rem;
}

.checker-failures__category {
  font-weight: 800;
}
</style>
