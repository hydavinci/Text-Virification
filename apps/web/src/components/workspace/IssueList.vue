<script setup lang="ts">
import IssueDetails from './IssueDetails.vue'
import type {
  IssueState,
  VerificationIssue
} from '../../types/verification'
import type {
  IssueLayerFilter,
  IssueSeverityFilter
} from '../../composables/useIssueNavigation'

interface LayerOption {
  id: string
  name: string
}

withDefaults(
  defineProps<{
    issues: readonly VerificationIssue[]
    selectedIssueId: string | null
    issueStates: Readonly<Record<string, IssueState>>
    selectedSuggestions: Readonly<Record<string, string | null>>
    selectedLayer?: IssueLayerFilter
    selectedSeverity?: IssueSeverityFilter
    layerOptions?: readonly LayerOption[]
    typeLabels?: Readonly<Record<string, string>>
  }>(),
  {
    selectedLayer: 'all',
    selectedSeverity: 'all',
    layerOptions: () => [],
    typeLabels: () => ({})
  }
)

const emit = defineEmits<{
  'select-issue': [issueId: string]
  'update:selected-layer': [layer: IssueLayerFilter]
  'update:selected-severity': [severity: IssueSeverityFilter]
  'update:suggestion': [issueId: string, suggestion: string | null]
  'set-state': [issueId: string, state: IssueState]
}>()

function activateIssue(issueId: string): void {
  emit('select-issue', issueId)
}

function updateLayer(event: Event): void {
  if (event.target instanceof HTMLSelectElement) {
    emit('update:selected-layer', event.target.value)
  }
}

function updateSeverity(event: Event): void {
  if (!(event.target instanceof HTMLSelectElement)) {
    return
  }
  switch (event.target.value) {
    case 'all':
    case 'error':
    case 'warning':
    case 'info':
      emit('update:selected-severity', event.target.value)
  }
}
</script>

<template>
  <div class="issue-list-shell">
    <div class="filters">
      <label>
        <span>检查层级</span>
        <select
          :value="selectedLayer"
          aria-label="检查层级"
          @change="updateLayer"
        >
          <option value="all">全部层级</option>
          <option
            v-for="layer in layerOptions"
            :key="layer.id"
            :value="layer.id"
          >
            {{ layer.name }}
          </option>
        </select>
      </label>
      <label>
        <span>问题级别</span>
        <select
          :value="selectedSeverity"
          aria-label="问题级别"
          @change="updateSeverity"
        >
          <option value="all">全部级别</option>
          <option value="error">错误</option>
          <option value="warning">警告</option>
          <option value="info">建议</option>
        </select>
      </label>
    </div>

    <div class="issue-list" aria-label="问题列表">
      <article
        v-for="issue in issues"
        :key="issue.issue_id"
        class="issue-card"
        :class="[
          issue.severity,
          issueStates[issue.issue_id] ?? 'pending',
          { selected: selectedIssueId === issue.issue_id }
        ]"
      >
        <button
          type="button"
          class="issue-select"
          :aria-label="`定位问题：${issue.message}`"
          :aria-current="
            selectedIssueId === issue.issue_id ? 'true' : undefined
          "
          :data-issue-id="issue.issue_id"
          data-issue-role="list"
          @click="activateIssue(issue.issue_id)"
          @keydown.enter.prevent="activateIssue(issue.issue_id)"
          @keydown.space.prevent="activateIssue(issue.issue_id)"
        >
          <span>{{ typeLabels[issue.type] ?? issue.type }}</span>
          <span>
            {{
              layerOptions.find((layer) => layer.id === issue.layer)?.name ??
              issue.layer
            }}
          </span>
          <span class="severity">{{ issue.severity }}</span>
        </button>

        <IssueDetails
          :issue="issue"
          :selected-suggestion="selectedSuggestions[issue.issue_id]"
          @update:suggestion="
            emit('update:suggestion', issue.issue_id, $event)
          "
        />

        <div class="issue-actions" aria-label="问题处理">
          <button
            class="accept"
            type="button"
            @click="emit('set-state', issue.issue_id, 'accepted')"
          >
            接受
          </button>
          <button
            class="reject"
            type="button"
            @click="emit('set-state', issue.issue_id, 'rejected')"
          >
            忽略
          </button>
          <button
            class="undo"
            type="button"
            @click="emit('set-state', issue.issue_id, 'pending')"
          >
            撤销
          </button>
        </div>
      </article>
      <div v-if="!issues.length" class="empty-state">
        当前筛选条件下没有问题
      </div>
    </div>
  </div>
</template>

<style scoped>
.issue-list-shell {
  display: flex;
  flex: 1;
  min-height: 0;
  flex-direction: column;
}

.filters {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 10px;
  border-bottom: 1px solid var(--border);
}

.filters label {
  display: grid;
  gap: 3px;
  color: var(--muted);
  font-size: 10px;
}

.filters select {
  min-width: 0;
}

.issue-list {
  flex: 1;
  min-height: 0;
  padding: 10px;
  overflow: auto;
}

.issue-card {
  margin-bottom: 9px;
  padding: 13px;
  border: 1px solid var(--border);
  border-left: 4px solid #f59e0b;
  border-radius: 12px;
  background: var(--surface);
}

.issue-card.error {
  border-left-color: #ef4444;
}

.issue-card.info {
  border-left-color: #3b82f6;
}

.issue-card.accepted {
  background: color-mix(in srgb, #dcfce7 46%, var(--surface));
}

.issue-card.rejected {
  opacity: 0.58;
}

.issue-card.selected {
  outline: 2px solid #2563eb;
  outline-offset: -2px;
}

.issue-select {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.issue-select span {
  padding: 3px 7px;
  border-radius: 999px;
  color: var(--muted);
  background: var(--surface-2);
  font-size: 10px;
  font-weight: 800;
}

.issue-select .severity {
  margin-left: auto;
  text-transform: uppercase;
}

.issue-select:focus-visible {
  border-radius: 7px;
  outline: 3px solid #2563eb;
  outline-offset: 3px;
}

.issue-actions {
  display: flex;
  gap: 7px;
  margin-top: 10px;
}

.issue-actions button {
  padding: 5px 10px;
  border: 0;
  border-radius: 7px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 800;
}

.issue-actions button:focus-visible {
  outline: 3px solid #2563eb;
  outline-offset: 2px;
}

.issue-actions .accept {
  color: #15803d;
  background: #dcfce7;
}

.issue-actions .reject {
  color: #be123c;
  background: #fff1f2;
}

.issue-actions .undo {
  color: var(--muted);
  background: var(--surface-2);
}

.empty-state {
  padding: 40px 10px;
  color: var(--muted);
  text-align: center;
}
</style>
