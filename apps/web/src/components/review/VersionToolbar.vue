<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'

import type { DocumentVersion, DocumentViewMode } from '../../types/revisions'

type EditableDocumentMode = DocumentViewMode | 'edit'

const VIEW_MODES: DocumentViewMode[] = ['original', 'modified', 'diff']

const props = defineProps<{
  versions: DocumentVersion[]
  activeVersionId: string | null
  selectedVersionId: string | null
  mode: EditableDocumentMode
  editing: boolean
  draftActive: boolean
  busy: boolean
}>()

const emit = defineEmits<{
  selectVersion: [versionId: string]
  setMode: [mode: DocumentViewMode]
  edit: []
}>()

const tabButtons = ref<HTMLButtonElement[]>([])
const selectedVersion = computed(
  () =>
    props.versions.find((version) => version.version_id === props.selectedVersionId) ??
    null
)
const isHistorical = computed(
  () =>
    selectedVersion.value !== null &&
    selectedVersion.value.version_id !== props.activeVersionId
)
const canStartDraft = computed(
  () =>
    selectedVersion.value?.status === 'succeeded' &&
    !props.editing &&
    !props.draftActive &&
    !props.busy
)
const controlsLocked = computed(() => props.busy || props.draftActive)
const selectedTabMode = computed<DocumentViewMode>(() =>
  props.mode === 'edit' ? 'original' : props.mode
)
const editLabel = computed(() =>
  isHistorical.value ? '从此版本创建新版本' : '编辑当前版本'
)

function versionLabel(version: DocumentVersion): string {
  return version.version_id === props.activeVersionId
    ? `版本 ${version.revision_number}（当前）`
    : `版本 ${version.revision_number}（历史，只读）`
}

function tabLabel(mode: DocumentViewMode): string {
  switch (mode) {
    case 'original':
      return '原文'
    case 'modified':
      return '修改后'
    case 'diff':
      return '差异'
  }
}

function tabindexForMode(mode: DocumentViewMode): 0 | -1 {
  if (!controlsLocked.value && selectedTabMode.value === mode) {
    return 0
  }
  return -1
}

function onSelectVersion(event: Event): void {
  const target = event.target
  if (target instanceof HTMLSelectElement && target.value) {
    emit('selectVersion', target.value)
  }
}

function onTabKeydown(event: KeyboardEvent, mode: DocumentViewMode): void {
  if (event.key !== 'ArrowRight' && event.key !== 'ArrowLeft') {
    return
  }
  event.preventDefault()
  const currentIndex = VIEW_MODES.indexOf(mode)
  const offset = event.key === 'ArrowRight' ? 1 : -1
  const nextMode = VIEW_MODES[(currentIndex + offset + VIEW_MODES.length) % VIEW_MODES.length]
  if (nextMode) {
    emit('setMode', nextMode)
    void nextTick(() => tabButtons.value[VIEW_MODES.indexOf(nextMode)]?.focus())
  }
}
</script>

<template>
  <section class="version-toolbar" aria-label="版本和文档视图">
    <label class="version-toolbar__version">
      <span>版本</span>
      <select
        aria-label="版本"
        :value="selectedVersionId ?? ''"
        :disabled="controlsLocked || versions.length === 0"
        @change="onSelectVersion"
      >
        <option
          v-for="version in versions"
          :key="version.version_id"
          :value="version.version_id"
        >
          {{ versionLabel(version) }}
        </option>
      </select>
    </label>

    <div class="version-toolbar__tabs" role="tablist" aria-label="文档视图">
      <button
        v-for="viewMode in VIEW_MODES"
        :key="viewMode"
        type="button"
        role="tab"
        :data-mode="viewMode"
        :aria-selected="selectedTabMode === viewMode ? 'true' : 'false'"
        :tabindex="tabindexForMode(viewMode)"
        :disabled="controlsLocked"
        ref="tabButtons"
        @click="emit('setMode', viewMode)"
        @keydown="onTabKeydown($event, viewMode)"
      >
        {{ tabLabel(viewMode) }}
      </button>
    </div>

    <button
      type="button"
      name="edit-version"
      class="version-toolbar__edit"
      :disabled="!canStartDraft"
      @click="emit('edit')"
    >
      {{ editLabel }}
    </button>

    <span v-if="isHistorical" class="version-toolbar__readonly">只读</span>
  </section>
</template>

<style scoped>
.version-toolbar {
  display: flex;
  align-items: end;
  justify-content: space-between;
  gap: var(--review-space-3);
  padding: var(--review-space-3) calc(var(--review-space-4) + 2px);
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1px solid var(--review-border);
}

.version-toolbar__version {
  display: grid;
  min-width: 160px;
  gap: 4px;
  color: var(--review-text-muted);
  font-size: 0.76rem;
  font-weight: 700;
}

.version-toolbar__version select {
  min-width: 0;
  color: var(--review-text);
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 4px);
}

.version-toolbar__tabs {
  display: inline-flex;
  padding: 3px;
  background: var(--review-accent-soft);
  border-radius: var(--review-panel-radius);
}

.version-toolbar__tabs button,
.version-toolbar__edit {
  min-height: 44px;
  padding: 0 var(--review-space-3);
  color: var(--review-accent);
  font-weight: 800;
  white-space: nowrap;
  background: transparent;
  border: 0;
  border-radius: calc(var(--review-panel-radius) - 5px);
  cursor: pointer;
}

.version-toolbar__tabs button[aria-selected='true'] {
  color: var(--review-text);
  background: var(--review-surface);
  box-shadow: 0 2px 8px rgba(44, 57, 88, 0.12);
}

.version-toolbar__edit {
  background: var(--review-accent);
  color: #fff;
}

.version-toolbar__edit:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

.version-toolbar__readonly {
  align-self: center;
  color: var(--review-text-muted);
  font-size: 0.78rem;
  font-weight: 800;
}

@media (max-width: 680px) {
  .version-toolbar {
    align-items: stretch;
    flex-direction: column;
  }

  .version-toolbar__tabs {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
