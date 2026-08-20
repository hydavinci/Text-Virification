<script setup lang="ts">
import { computed, inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { DocumentBlock, Issue } from '../../types/analysis'
import type { FileType } from '../../types/review'
import DocumentHeader from './DocumentHeader.vue'
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

const props = defineProps<{
  sourceName: string
  fileType: FileType
  totalIssues: number | null
  summaryLoading: boolean
  summaryError: string | null
  blocks: DocumentBlock[]
  issues: Issue[]
  selectedIssueId: string | null
  selectedBlockId: string | null
  nextCursor: string | null
  loading: boolean
  error: string | null
}>()

const emit = defineEmits<{
  selectHighlight: [issueId: string]
  loadNext: []
  retrySummary: []
  retry: []
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
    return issue.suggestion ?? issue.original
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
    />

    <div v-if="error" class="document-viewer__error" data-testid="document-error" role="alert">
      <p>{{ error }}</p>
      <button type="button" data-testid="retry-document" @click="emit('retry')">
        重试文档内容
      </button>
    </div>

    <div class="document-viewer__page">
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

      <p v-if="!loading && !error && !blocks.length" class="document-viewer__empty">
        文档中没有可显示的文本块。
      </p>

      <div
        v-if="nextCursor"
        ref="sentinel"
        class="document-viewer__sentinel"
        data-testid="document-sentinel"
        aria-hidden="true"
      />
    </div>
  </article>
</template>

<style scoped>
.document-viewer {
  min-width: 0;
  height: 100%;
  min-height: 0;
  overflow: auto;
  background: #edf1f7;
  border: 1px solid #dfe5ef;
  border-radius: 16px;
}

@media (max-width: 1100px) {
  .document-viewer {
    height: auto;
  }
}

.document-viewer__page {
  width: min(100% - 36px, 760px);
  min-height: 680px;
  margin: 22px auto;
  padding: 64px 68px;
  background: #fff;
  box-shadow: 0 9px 28px rgba(44, 57, 88, 0.1);
}

.document-block {
  margin: 0 0 1.15em;
  padding: 4px 7px;
  color: #273044;
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
  color: #a53636;
  background: #fff;
  border: 1px solid #f0c8c8;
  border-radius: 10px;
}

.document-viewer__error p {
  margin: 0 0 10px;
}

.document-viewer__error button {
  min-height: 44px;
  padding: 7px 10px;
  color: #4256c9;
  font-weight: 700;
  background: #eef0ff;
  border: 0;
  border-radius: 8px;
  cursor: pointer;
}

.document-viewer__empty {
  color: #667085;
  text-align: center;
}

.document-viewer__sentinel {
  height: 1px;
}
</style>
