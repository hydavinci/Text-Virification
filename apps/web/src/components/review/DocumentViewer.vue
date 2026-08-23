<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { DocumentBlock, Issue } from '../../types/analysis'
import type { FileType } from '../../types/review'
import type {
  DerivedDiffBlock,
  DocumentVersion,
  DocumentViewMode,
  DraftBlock,
  VersionEvent
} from '../../types/revisions'
import DocumentDiff from './DocumentDiff.vue'
import DocumentEditor from './DocumentEditor.vue'
import DocumentHeader from './DocumentHeader.vue'
import VersionToolbar from './VersionToolbar.vue'
import {
  browserReviewIntersectionObserverFactory,
  reviewIntersectionObserverFactoryKey,
  type ReviewIntersectionObserver
} from './observer'

interface TextSegment {
  key: string
  text: string
  issueIds: string[]
  start: number
  end: number
  selectedBounds: boolean
}

interface BlockRenderModel {
  segments: TextSegment[]
}

interface NormalizedIssue {
  issue: Issue
  start: number
  end: number
}

interface OverlapComponent {
  issueIds: string[]
}

type EditableDocumentMode = DocumentViewMode | 'edit'

const props = defineProps<{
  sourceName: string
  fileType: FileType
  totalIssues: number | null
  summaryLoading: boolean
  summaryError: string | null
  versions: DocumentVersion[]
  activeVersionId: string | null
  selectedVersionId: string | null
  mode: EditableDocumentMode
  blocks: DocumentBlock[]
  modifiedBlocks: DocumentBlock[]
  diffBlocks: DerivedDiffBlock[]
  draftBlocks: DraftBlock[]
  issues: Issue[]
  selectedIssueId: string | null
  selectedBlockId: string | null
  nextCursor: string | null
  loading: boolean
  error: string | null
  derivedLoading: DocumentViewMode | null
  derivedError: string | null
  draftBusy: boolean
  draftError: string | null
  reanalysis: {
    status: VersionEvent['status']
    progress: number
    message: string
  } | null
  reanalysisError: string | null
}>()

const emit = defineEmits<{
  selectHighlight: [issueId: string]
  loadNext: []
  retrySummary: []
  retry: []
  processAnotherFile: []
  selectVersion: [versionId: string]
  setMode: [mode: DocumentViewMode]
  edit: []
  updateDraftBlock: [blockId: string, text: string]
  saveReanalyze: []
  discardDraft: []
  returnToDraft: []
  retryReanalysis: []
}>()

const observerFactory = inject(
  reviewIntersectionObserverFactoryKey,
  browserReviewIntersectionObserverFactory
)
const viewer = ref<HTMLElement | null>(null)
const sentinel = ref<Element | null>(null)
let observer: ReviewIntersectionObserver | null = null
let requestedCursor: string | null = null
let pendingHighlightFocusIssueId: string | null = null
let restoreFocusOnNextPointerClick = false
let active = true

const loadedParagraphCount = computed(
  () => props.blocks.filter(({ kind }) => kind === 'paragraph').length
)
const visibleModifiedBlocks = computed(() =>
  props.mode === 'modified' ? props.modifiedBlocks : []
)
const reanalysisFailed = computed(
  () => props.reanalysis?.status === 'failed' || props.reanalysisError !== null
)
const reanalysisMessage = computed(
  () => props.reanalysisError ?? props.reanalysis?.message ?? '版本重新检查失败。'
)
const reanalysisInProgress = computed(
  () =>
    props.reanalysis !== null &&
    props.reanalysis.status !== 'succeeded' &&
    props.reanalysis.status !== 'failed' &&
    props.reanalysisError === null
)

function issuesForBlock(blockId: string): Issue[] {
  return props.issues.filter((issue) => issue.block_id === blockId)
}

function connectedOverlapComponents(
  issues: NormalizedIssue[]
): Map<string, OverlapComponent> {
  const components = new Map<string, OverlapComponent>()
  let componentMembers: NormalizedIssue[] = []
  let componentEnd = -1

  function commitComponent(): void {
    if (!componentMembers.length) {
      return
    }

    const issueIds = componentMembers.map(({ issue }) => issue.issue_id)
    const component = { issueIds }
    for (const member of componentMembers) {
      components.set(member.issue.issue_id, component)
    }
    componentMembers = []
    componentEnd = -1
  }

  for (const issue of issues) {
    if (!componentMembers.length) {
      componentMembers = [issue]
      componentEnd = issue.end
      continue
    }

    if (issue.start < componentEnd) {
      componentMembers.push(issue)
      componentEnd = Math.max(componentEnd, issue.end)
      continue
    }

    commitComponent()
    componentMembers = [issue]
    componentEnd = issue.end
  }

  commitComponent()
  return components
}

function renderModelForBlock(block: DocumentBlock): BlockRenderModel {
  const points = Array.from(block.text)
  const normalizedIssues = issuesForBlock(block.block_id)
    .map((issue) => {
      const start = Math.max(0, Math.min(points.length, issue.start))
      const end = Math.max(start, Math.min(points.length, issue.end))
      return { issue, start, end }
    })
    .sort(
      (left, right) =>
        left.start - right.start ||
        left.end - right.end ||
        left.issue.issue_id.localeCompare(right.issue.issue_id)
    )
  const renderableIssues = normalizedIssues.filter(
    (normalized) => normalized.end > normalized.start
  )
  const componentByIssueId = connectedOverlapComponents(renderableIssues)

  if (!renderableIssues.length) {
    return {
      segments: [
        {
          key: `${block.block_id}-text`,
          text: block.text,
          issueIds: [],
          start: 0,
          end: points.length,
          selectedBounds: false
        }
      ]
    }
  }

  const boundaries = Array.from(
    new Set([
      0,
      points.length,
      ...renderableIssues.flatMap(({ start, end }) => [start, end])
    ])
  ).sort((left, right) => left - right)
  const atomicSegments: TextSegment[] = []

  for (let index = 1; index < boundaries.length; index += 1) {
    const start = boundaries[index - 1] ?? 0
    const end = boundaries[index] ?? start
    const overlappingIssues = renderableIssues.filter(
      (normalized) => normalized.start < end && normalized.end > start
    )
    const issueIds =
      overlappingIssues[0] === undefined
        ? []
        : componentByIssueId.get(overlappingIssues[0].issue.issue_id)?.issueIds ??
          overlappingIssues.map(({ issue }) => issue.issue_id)

    atomicSegments.push({
      key: `${block.block_id}-${start}-${end}`,
      text: points.slice(start, end).join(''),
      issueIds,
      start,
      end,
      selectedBounds: false
    })
  }

  const selectedIssue = props.selectedIssueId
    ? renderableIssues.find(
        (normalized) => normalized.issue.issue_id === props.selectedIssueId
      )
    : undefined

  if (!selectedIssue) {
    return { segments: atomicSegments }
  }

  const overlapComponent = componentByIssueId.get(selectedIssue.issue.issue_id)
  const overlapKey = overlapComponent?.issueIds.join('-') ?? selectedIssue.issue.issue_id
  const segments: TextSegment[] = []

  for (let index = 0; index < atomicSegments.length; index += 1) {
    const segment = atomicSegments[index]
    if (!segment) {
      continue
    }

    const overlapsSelected =
      segment.start < selectedIssue.end && segment.end > selectedIssue.start

    if (!overlapsSelected) {
      segments.push(segment)
      continue
    }

    let cursor = index

    while (cursor < atomicSegments.length) {
      const candidate = atomicSegments[cursor]
      if (
        !candidate ||
        candidate.start >= selectedIssue.end ||
        candidate.end <= selectedIssue.start
      ) {
        break
      }

      cursor += 1
    }

    segments.push({
      key: `${block.block_id}-overlap-${overlapKey}`,
      text: previewText(selectedIssue.issue),
      issueIds: overlapComponent?.issueIds ?? [selectedIssue.issue.issue_id],
      start: selectedIssue.start,
      end: selectedIssue.end,
      selectedBounds: true
    })
    index = cursor - 1
  }

  return {
    segments
  }
}

function previewText(issue: Issue): string {
  if (issue.decision?.action === 'accepted') {
    return issue.decision.replacement ?? issue.suggestion ?? issue.original
  }
  if (issue.decision?.action === 'custom') {
    return issue.decision.replacement
  }
  return issue.original
}

function nextIssueId(issueIds: string[]): string | null {
  if (!issueIds.length) {
    return null
  }

  const selectedIndex = props.selectedIssueId
    ? issueIds.indexOf(props.selectedIssueId)
    : -1
  const nextIndex = selectedIndex === -1 ? 0 : (selectedIndex + 1) % issueIds.length
  return issueIds[nextIndex] ?? null
}

function activateSegment(issueIds: string[], restoreFocus = false): void {
  const issueId = nextIssueId(issueIds)
  if (issueId) {
    pendingHighlightFocusIssueId = restoreFocus ? issueId : null
    emit('selectHighlight', issueId)
  }
}

function onHighlightPointerDown(event: PointerEvent): void {
  restoreFocusOnNextPointerClick =
    event.currentTarget instanceof HTMLElement &&
    typeof document !== 'undefined' &&
    event.currentTarget === document.activeElement
}

function onHighlightClick(_event: MouseEvent, issueIds: string[]): void {
  const restoreFocus = restoreFocusOnNextPointerClick
  restoreFocusOnNextPointerClick = false
  activateSegment(issueIds, restoreFocus)
}

function onHighlightKeydown(event: KeyboardEvent, issueIds: string[]): void {
  if (event.key !== 'Enter' && event.key !== ' ' && event.key !== 'Spacebar') {
    return
  }

  event.preventDefault()
  activateSegment(issueIds, true)
}

function highlightLabel(segment: TextSegment): string {
  const text = segment.text.trim()
  const label = text || props.issues.find((issue) => segment.issueIds.includes(issue.issue_id))?.message || '高亮文本'
  const countLabel = segment.issueIds.length > 1 ? `（共 ${segment.issueIds.length} 个问题）` : ''
  return `选择问题：${label}${countLabel}`
}

function connectObserver(element: Element | null): void {
  observer?.disconnect()
  observer = null

  if (!element || !props.nextCursor) {
    return
  }

  observer = observerFactory((entries) => {
    if (
      entries.some((entry) => entry.isIntersecting) &&
      props.nextCursor &&
      props.nextCursor !== requestedCursor &&
      !props.loading
    ) {
      requestedCursor = props.nextCursor
      emit('loadNext')
    }
  })
  observer.observe(element)
}

function scrollWithinViewer(element: HTMLElement): void {
  const container = viewer.value
  if (!container) {
    return
  }

  if (container.scrollHeight <= container.clientHeight) {
    element.scrollIntoView?.({ block: 'center' })
    return
  }

  const containerRect = container.getBoundingClientRect()
  const elementRect = element.getBoundingClientRect()
  const top =
    container.scrollTop +
    elementRect.top -
    containerRect.top -
    (container.clientHeight - elementRect.height) / 2

  const nextTop = Math.max(0, top)
  if (typeof container.scrollTo === 'function') {
    container.scrollTo({ top: nextTop })
    return
  }

  container.scrollTop = nextTop
}

function focusSelectedHighlight(): void {
  viewer.value
    ?.querySelector<HTMLElement>('[data-highlight-selected="true"]')
    ?.focus()
}

defineExpose({ focusSelectedHighlight })

watch(sentinel, connectObserver)

watch(
  () => [props.selectedIssueId, props.selectedBlockId, props.blocks] as const,
  async ([issueId, blockId]) => {
    if (!issueId && !blockId) {
      return
    }
    await nextTick()
    if (!active) {
      return
    }
    if (issueId) {
      const highlight = viewer.value?.querySelector<HTMLElement>(
        '[data-highlight-selected="true"]'
      )

      if (highlight) {
        scrollWithinViewer(highlight)
        if (pendingHighlightFocusIssueId === issueId) {
          highlight.focus()
          pendingHighlightFocusIssueId = null
        }
        return
      }
    }

    const block = blockId
      ? viewer.value?.querySelector<HTMLElement>(`[data-block-id="${blockId}"]`)
      : null
    if (block) {
      scrollWithinViewer(block)
    }
  },
  { flush: 'post' }
)

onBeforeUnmount(() => {
  active = false
  observer?.disconnect()
})
</script>

<template>
  <article ref="viewer" class="document-viewer" aria-label="文档内容">
    <DocumentHeader
      :source-name="sourceName"
      :file-type="fileType"
      :loaded-paragraph-count="loadedParagraphCount"
      :total-issues="totalIssues"
      :loading="summaryLoading"
      :error="summaryError"
      @retry="emit('retrySummary')"
      @process-another-file="emit('processAnotherFile')"
    />

    <VersionToolbar
      :versions="versions"
      :active-version-id="activeVersionId"
      :selected-version-id="selectedVersionId"
      :mode="mode"
      :editing="mode === 'edit'"
      :busy="draftBusy"
      @select-version="emit('selectVersion', $event)"
      @set-mode="emit('setMode', $event)"
      @edit="emit('edit')"
    />

    <div
      v-if="reanalysisInProgress"
      class="document-viewer__progress"
      role="status"
      data-testid="reanalysis-progress"
    >
      <p>{{ reanalysis?.message || '正在重新检查版本…' }}</p>
      <progress :value="reanalysis?.progress ?? 0" max="100">
        {{ reanalysis?.progress ?? 0 }}%
      </progress>
    </div>

    <div
      v-if="reanalysisFailed"
      class="document-viewer__error"
      data-testid="reanalysis-failure"
      role="alert"
    >
      <p>{{ reanalysisMessage }}</p>
      <button type="button" name="return-to-draft" @click="emit('returnToDraft')">
        返回草稿
      </button>
      <button type="button" name="retry-reanalysis" @click="emit('retryReanalysis')">
        重试
      </button>
    </div>

    <div v-if="error" class="document-viewer__error" data-testid="document-error" role="alert">
      <p>{{ error }}</p>
      <button type="button" data-testid="retry-document" @click="emit('retry')">
        重试文档内容
      </button>
    </div>

    <div class="document-viewer__page">
      <DocumentEditor
        v-if="mode === 'edit'"
        :blocks="blocks"
        :draft-blocks="draftBlocks"
        :busy="draftBusy"
        :error="draftError"
        @update-block="(blockId, text) => emit('updateDraftBlock', blockId, text)"
        @save-reanalyze="emit('saveReanalyze')"
        @discard="emit('discardDraft')"
      />

      <template v-else-if="mode === 'modified'">
        <p
          v-for="block in visibleModifiedBlocks"
          :key="block.block_id"
          class="document-block"
          :data-block-id="block.block_id"
        >
          {{ block.text }}
        </p>
      </template>

      <DocumentDiff v-else-if="mode === 'diff'" :blocks="diffBlocks" />

      <template v-else>
        <p
          v-for="block in blocks"
          :key="block.block_id"
          class="document-block"
          :class="{ 'document-block--active': block.block_id === selectedBlockId }"
          :data-block-id="block.block_id"
        >
          <template v-for="segment in renderModelForBlock(block).segments" :key="segment.key">
            <span
              v-if="segment.issueIds.length"
              class="document-highlight-range"
              :class="{
                'document-highlight-range--active': segment.selectedBounds
              }"
              role="button"
              tabindex="0"
              :data-highlight-range-issue-ids="segment.issueIds.join(' ')"
              :data-highlight-selected="segment.selectedBounds ? 'true' : undefined"
              :aria-label="highlightLabel(segment)"
              :aria-current="segment.selectedBounds ? 'true' : 'false'"
              @pointerdown="onHighlightPointerDown"
              @click="onHighlightClick($event, segment.issueIds)"
              @keydown="onHighlightKeydown($event, segment.issueIds)"
            >{{ segment.text }}</span>
            <template v-else>{{ segment.text }}</template>
          </template>
        </p>
      </template>

      <p v-if="!loading && !error && !blocks.length" class="document-viewer__empty">
        文档中没有可显示的文本块。
      </p>

      <div
        v-if="mode === 'original' && nextCursor"
        ref="sentinel"
        class="document-viewer__sentinel"
        data-testid="document-sentinel"
        aria-hidden="true"
      />

      <p
        v-if="(mode === 'modified' || mode === 'diff') && derivedLoading === mode"
        class="document-viewer__empty"
        role="status"
      >
        正在加载预览…
      </p>

      <p
        v-if="(mode === 'modified' || mode === 'diff') && derivedError"
        class="document-viewer__error"
        role="alert"
      >
        {{ derivedError }}
      </p>
    </div>
  </article>
</template>

<style scoped>
.document-viewer {
  min-width: 0;
  height: 100%;
  min-height: 0;
  overflow: auto;
  background: var(--review-canvas);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) + var(--review-space-1));
}

@media (max-width: 1279px) {
  .document-viewer {
    height: auto;
  }
}

.document-viewer__page {
  width: min(100% - 36px, 760px);
  min-height: 680px;
  margin: 22px auto;
  padding: 64px 68px;
  background: var(--review-surface);
  box-shadow: 0 9px 28px rgba(44, 57, 88, 0.1);
}

.document-block {
  margin: 0 0 1.15em;
  padding: 4px 7px;
  color: var(--review-text);
  font-family: "Noto Serif SC", "Songti SC", SimSun, serif;
  font-size: 1rem;
  line-height: 1.9;
  border-left: 3px solid transparent;
  border-radius: 5px;
  white-space: pre-wrap;
}

.document-block--active {
  background: #f3f4ff;
  border-left-color: #6579e8;
}

.document-highlight-range {
  position: relative;
  background: #fff0a8;
  border-radius: 2px;
  cursor: pointer;
}

.document-highlight-range::after {
  content: "";
  position: absolute;
  top: 50%;
  left: 50%;
  min-inline-size: 44px;
  min-block-size: 44px;
  inline-size: 100%;
  transform: translate(-50%, -50%);
}

.document-highlight-range:hover,
.document-highlight-range:focus-visible {
  background: #ffe47f;
}

.document-highlight-range:focus-visible {
  outline: 2px solid #bd7d18;
  outline-offset: 2px;
}

.document-highlight-range--active {
  background: #ffd56a;
  outline: 2px solid #bd7d18;
  outline-offset: 1px;
}

.document-viewer__error {
  margin: 18px;
  padding: 14px;
  color: var(--review-danger);
  background: var(--review-surface);
  border: 1px solid #f0c8c8;
  border-radius: calc(var(--review-panel-radius) - 2px);
}

.document-viewer__progress {
  margin: 18px;
  padding: 14px;
  color: var(--review-text);
  background: var(--review-surface);
  border: 1px solid var(--review-border);
  border-radius: calc(var(--review-panel-radius) - 2px);
}

.document-viewer__error p {
  margin: 0 0 10px;
}

.document-viewer__progress p {
  margin: 0 0 10px;
  color: var(--review-text-muted);
  font-weight: 700;
}

.document-viewer__progress progress {
  width: 100%;
}

.document-viewer__error button {
  min-height: 44px;
  padding: 7px 10px;
  color: var(--review-accent);
  font-weight: 700;
  white-space: nowrap;
  background: var(--review-accent-soft);
  border: 0;
  border-radius: calc(var(--review-panel-radius) - 4px);
  cursor: pointer;
}

.document-viewer__empty {
  color: var(--review-text-muted);
  text-align: center;
}

.document-viewer__sentinel {
  height: 1px;
}
</style>
