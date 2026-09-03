<script setup lang="ts">
import { computed } from 'vue'

import type { VerificationIssue } from '../../types/verification'

const props = defineProps<{
  issue: VerificationIssue
  selectedSuggestion?: string | null
}>()

const emit = defineEmits<{
  'update:suggestion': [suggestion: string | null]
}>()

const effectiveSuggestion = computed(() =>
  props.selectedSuggestion === undefined
    ? props.issue.suggestion
    : props.selectedSuggestion
)

const alternatives = computed<readonly string[]>(() => {
  const seen = new Set<string>()
  const values: string[] = []
  for (const alternative of props.issue.alternatives ?? []) {
    if (
      alternative === props.issue.suggestion ||
      seen.has(alternative)
    ) {
      continue
    }
    seen.add(alternative)
    values.push(alternative)
  }
  return values
})

const selectableSuggestions = computed<readonly (string | null)[]>(() => {
  const values: (string | null)[] = [props.issue.suggestion]
  for (const alternative of alternatives.value) {
    if (!values.includes(alternative)) {
      values.push(alternative)
    }
  }
  return values
})

function suggestionLabel(suggestion: string | null): string {
  if (suggestion === null) {
    return '无自动建议'
  }
  return suggestion === '' ? '（删除）' : suggestion
}

function updateSuggestion(event: Event): void {
  if (event.target instanceof HTMLSelectElement) {
    const selectedIndex = Number(event.target.value)
    const suggestion = selectableSuggestions.value[selectedIndex]
    if (
      Number.isInteger(selectedIndex) &&
      selectedIndex >= 0 &&
      selectedIndex < selectableSuggestions.value.length &&
      suggestion !== undefined
    ) {
      emit('update:suggestion', suggestion)
    }
  }
}
</script>

<template>
  <div class="issue-details">
    <div class="diff">
      <del data-original>{{ issue.original || '（空）' }}</del>
      <span aria-hidden="true">→</span>
      <span data-suggestion>{{ suggestionLabel(effectiveSuggestion) }}</span>
    </div>

    <label v-if="alternatives.length" class="suggestion-picker">
      <span>选择修改建议</span>
      <select
        :value="
          selectableSuggestions.findIndex(
            (suggestion) => suggestion === effectiveSuggestion
          )
        "
        aria-label="选择修改建议"
        @change="updateSuggestion"
      >
        <option
          v-for="(suggestion, index) in selectableSuggestions"
          :key="`${index}-${suggestion ?? 'manual'}`"
          :value="index"
        >
          {{ suggestionLabel(suggestion) }}
        </option>
      </select>
    </label>

    <div v-if="alternatives.length" class="alternatives">
      <strong>其他建议</strong>
      <ul>
        <li
          v-for="(alternative, index) in alternatives"
          :key="alternative"
          data-alternative
        >
          <span :data-recommended="index === 0 ? '' : undefined">
            {{ suggestionLabel(alternative) }}
          </span>
          <small v-if="index === 0">推荐</small>
        </li>
      </ul>
    </div>

    <p>{{ issue.description }}</p>
    <blockquote>{{ issue.context }}</blockquote>
    <p v-if="issue.review_reason" class="review-note">
      语义复核：{{ issue.review_reason }}
    </p>
  </div>
</template>

<style scoped>
.diff {
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 11px 0;
  font-weight: 800;
}

.diff del {
  color: #dc2626;
}

[data-suggestion] {
  color: #059669;
}

.suggestion-picker {
  display: grid;
  gap: 4px;
  margin: 8px 0;
  color: var(--muted);
  font-size: 11px;
}

.suggestion-picker select {
  max-width: 100%;
  padding: 5px;
}

.alternatives {
  margin: 10px 0;
  font-size: 11px;
}

.alternatives ul {
  margin: 5px 0 0;
  padding-left: 20px;
}

.alternatives li {
  margin: 3px 0;
}

.alternatives small {
  margin-left: 6px;
  color: #2563eb;
  font-weight: 800;
}

p {
  margin: 7px 0;
  font-size: 12px;
}

blockquote {
  margin: 8px 0;
  padding: 8px 10px;
  border-left: 2px solid var(--border);
  color: var(--muted);
  background: var(--surface-2);
  font-size: 11px;
}

.review-note {
  color: #7c3aed;
}
</style>
