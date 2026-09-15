<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'

import IssueDetails from './IssueDetails.vue'
import { vSelectMenu } from '../../directives/selectMenu'
import { revealWithinPane } from '../../utils/revealWithinPane'
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

const props = withDefaults(
  defineProps<{
    issues: readonly VerificationIssue[]
    selectedIssueId: string | null
    revealKey?: string
    issueStates: Readonly<Record<string, IssueState>>
    selectedSuggestions: Readonly<Record<string, string | null>>
    selectedLayer?: IssueLayerFilter
    selectedSeverity?: IssueSeverityFilter
    layerOptions?: readonly LayerOption[]
    typeLabels?: Readonly<Record<string, string>>
    disabled?: boolean
  }>(),
  {
    selectedLayer: 'all',
    selectedSeverity: 'all',
    layerOptions: () => [],
    typeLabels: () => ({}),
    disabled: false
  }
)

const emit = defineEmits<{
  'select-issue': [issueId: string]
  'update:selected-layer': [layer: IssueLayerFilter]
  'update:selected-severity': [severity: IssueSeverityFilter]
  'update:suggestion': [issueId: string, suggestion: string | null]
  'set-state': [issueId: string, state: IssueState]
}>()

const root = ref<HTMLElement | null>(null)

function activateIssue(issueId: string): void {
  emit('select-issue', issueId)
}

function summarySuggestion(issue: VerificationIssue): string {
  const selected = props.selectedSuggestions[issue.issue_id]
  const suggestion = selected === undefined ? issue.suggestion : selected
  if (suggestion === null) return '需人工核对'
  if (suggestion === '') return '（删除）'
  return suggestion.trim() ? suggestion : '（空白字符）'
}

async function scrollSelectedIssue(issueId: string | null): Promise<void> {
  if (issueId === null) {
    return
  }
  await nextTick()
  if (props.selectedIssueId !== issueId) {
    return
  }
  const control = Array.from(
    root.value?.querySelectorAll<HTMLElement>('[data-issue-id]') ?? []
  ).find(
    (element) =>
      element.dataset.issueId === issueId &&
      element.dataset.issueRole === 'list'
  )
  if (control) {
    revealWithinPane(control, root.value?.querySelector<HTMLElement>('.issue-list') ?? null)
    const sidebar = root.value?.closest<HTMLElement>('.issues-panel')
    if (sidebar) {
      revealWithinPane(control, sidebar)
    }
  }
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

watch(
  () => [props.selectedIssueId, props.revealKey] as const,
  ([issueId]) => {
    void scrollSelectedIssue(issueId)
  },
  { flush: 'post', immediate: true }
)
</script>

<template>
  <div ref="root" class="issue-list-shell">
    <div class="filters">
      <label>
        <span>检查层级</span>
        <select
          v-select-menu
          class="ui-field"
          :value="selectedLayer"
          aria-label="检查层级"
          :disabled="disabled"
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
          v-select-menu
          class="ui-field"
          :value="selectedSeverity"
          aria-label="问题级别"
          :disabled="disabled"
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
          :aria-expanded="selectedIssueId === issue.issue_id"
          :data-issue-id="issue.issue_id"
          data-issue-role="list"
          :disabled="disabled"
          @click="activateIssue(issue.issue_id)"
          @keydown.enter.prevent="activateIssue(issue.issue_id)"
          @keydown.space.prevent="activateIssue(issue.issue_id)"
        >
          <span class="issue-meta">
            <span>{{ typeLabels[issue.type] ?? issue.type }}</span>
            <span class="severity">{{ { error: '错误', warning: '警告', info: '建议' }[issue.severity] }}</span>
            <span v-if="issueStates[issue.issue_id] === 'accepted'">已接受</span>
            <span v-else-if="issueStates[issue.issue_id] === 'rejected'">已忽略</span>
          </span>
          <span class="issue-message">{{ issue.message }}</span>
          <span v-if="selectedIssueId !== issue.issue_id" class="issue-original">
            {{ issue.original.trim() ? issue.original : '（空白字符）' }}
            <span aria-hidden="true"> → </span>{{ summarySuggestion(issue) }}
          </span>
        </button>

        <IssueDetails
          v-if="selectedIssueId === issue.issue_id"
          :issue="issue"
          :selected-suggestion="selectedSuggestions[issue.issue_id]"
          :disabled="disabled"
          @update:suggestion="
            emit('update:suggestion', issue.issue_id, $event)
          "
        />

        <div v-if="selectedIssueId === issue.issue_id" class="issue-actions" aria-label="问题处理">
          <button
            class="accept ui-button ui-button--primary"
            type="button"
            :disabled="disabled"
            @click="emit('set-state', issue.issue_id, 'accepted')"
          >
            接受
          </button>
          <button
            class="reject ui-button ui-button--quiet"
            type="button"
            :disabled="disabled"
            @click="emit('set-state', issue.issue_id, 'rejected')"
          >
            忽略
          </button>
          <button
            class="undo ui-button ui-button--quiet"
            type="button"
            :disabled="disabled"
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
  gap: 10px;
  padding: 14px 12px;
  border-bottom: 1px solid var(--border);
}

.filters label {
  display: grid;
  gap: 6px;
  color: var(--muted);
  font-size: 12px;
}

.filters select {
  min-width: 0;
  width: 100%;
  padding-inline: 6px;
}

.issue-list {
  flex: 1;
  min-height: 0;
  padding: 0;
  overflow: auto;
}

.issue-card {
  margin: 0;
  padding: 16px;
  border: 0;
  border-bottom: 1px solid var(--border);
  border-left: 1px solid transparent;
  border-radius: 0;
  background: var(--surface);
  transition: background-color .15s;
}
.issue-card:hover { background: var(--surface-2); }

.issue-card.accepted {
  color: var(--muted);
}

.issue-card.rejected {
  color: var(--muted);
}

.issue-card.selected {
  border-left-color: var(--primary);
  background: var(--primary-soft);
}

.issue-select {
  width: 100%;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 8px;
  padding: 0;
  border: 0;
  color: inherit;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.issue-meta { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; color: var(--muted); font-size: 12px; }
.severity { margin-left: auto; font-size: 12px; }
.error .severity { color: var(--danger); }
.warning .severity { color: var(--warning); }
.info .severity { color: var(--muted); }
.issue-message { color: var(--text); font-size: 14px; font-weight: 500; line-height: 1.65; overflow-wrap: anywhere; }
.issue-original { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--muted); }

.issue-select:focus-visible {
  border-radius: 7px;
}

.issue-actions {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-top: 14px;
  padding-top: 12px;
  border-top: 1px solid var(--border);
}
.issue-actions button { padding-inline: 10px; }

.empty-state {
  margin: 12px 0;
  padding: 32px 14px;
  color: var(--muted);
  font-size: 13px;
  line-height: 1.8;
  text-align: center;
}
</style>
