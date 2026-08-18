<script setup lang="ts">
import { inject, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import type { DocumentBlock, Issue } from '../../types/analysis'
import {
  browserReviewIntersectionObserverFactory,
  reviewIntersectionObserverFactoryKey,
  type ReviewIntersectionObserver
} from './observer'

interface TextSegment {
  key: string
  text: string
  issueIds: string[]
  endingIssues: Issue[]
}

interface BlockRenderModel {
  leadingIssues: Issue[]
  segments: TextSegment[]
}

const props = defineProps<{
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
let active = true

function issuesForBlock(blockId: string): Issue[] {
  return props.issues.filter((issue) => issue.block_id === blockId)
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

  if (!normalizedIssues.length) {
    return {
      leadingIssues: [],
      segments: [
        {
          key: `${block.block_id}-text`,
          text: block.text,
          issueIds: [],
          endingIssues: []
        }
      ]
    }
  }

  const boundaries = Array.from(
    new Set([
      0,
      points.length,
      ...normalizedIssues.flatMap(({ start, end }) => [start, end])
    ])
  ).sort((left, right) => left - right)
  const segments: TextSegment[] = []

  for (let index = 1; index < boundaries.length; index += 1) {
    const start = boundaries[index - 1] ?? 0
    const end = boundaries[index] ?? start
    const issueIds = normalizedIssues
      .filter((normalized) => normalized.start < end && normalized.end > start)
      .map(({ issue }) => issue.issue_id)
    const endingIssues = normalizedIssues
      .filter((normalized) => normalized.end === end)
      .map(({ issue }) => issue)

    segments.push({
      key: `${block.block_id}-${start}-${end}`,
      text: points.slice(start, end).join(''),
      issueIds,
      endingIssues
    })
  }

  return {
    leadingIssues: normalizedIssues
      .filter((normalized) => normalized.end === 0)
      .map(({ issue }) => issue),
    segments
  }
}

function isSelectedRange(issueIds: string[]): boolean {
  return props.selectedIssueId !== null && issueIds.includes(props.selectedIssueId)
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

function segmentText(segment: TextSegment): string {
  const selectedIssueId = props.selectedIssueId
  if (!selectedIssueId || !segment.issueIds.includes(selectedIssueId)) {
    return segment.text
  }

  const endingIssue = segment.endingIssues.find(
    (issue) => issue.issue_id === selectedIssueId
  )
  return endingIssue ? previewText(endingIssue) : ''
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
      const highlight = Array.from(
        viewer.value?.querySelectorAll<HTMLElement>('[data-highlight-issue-id]') ?? []
      ).find((element) => element.dataset.highlightIssueId === issueId)

      if (highlight) {
        highlight.scrollIntoView?.({ block: 'center' })
        return
      }
    }

    const block = blockId
      ? viewer.value?.querySelector<HTMLElement>(`[data-block-id="${blockId}"]`)
      : null
    block?.scrollIntoView?.({ block: 'center' })
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
    <div class="document-viewer__heading">
      <div>
        <p>文档内容</p>
        <strong>{{ blocks.length }} 个已加载段落</strong>
      </div>
      <span v-if="loading" role="status">正在加载…</span>
    </div>

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
        <template
          v-for="issue in renderModelForBlock(block).leadingIssues"
          :key="`leading-${issue.issue_id}`"
        >
          <button
            type="button"
            class="document-highlight-control"
            :class="{
              'document-highlight-control--active': issue.issue_id === selectedIssueId
            }"
            :data-highlight-issue-id="issue.issue_id"
            :aria-label="`选择问题：${issue.original || issue.message}`"
            :aria-current="issue.issue_id === selectedIssueId ? 'true' : 'false'"
            :title="issue.message"
            @click="emit('selectHighlight', issue.issue_id)"
          >{{ issue.issue_id === selectedIssueId ? previewText(issue) : '' }}</button>
        </template>
        <template v-for="segment in renderModelForBlock(block).segments" :key="segment.key">
          <span
            v-if="segment.issueIds.length"
            class="document-highlight-range"
            :class="{
              'document-highlight-range--active': isSelectedRange(segment.issueIds)
            }"
            :data-highlight-range-issue-ids="segment.issueIds.join(' ')"
          >{{ segmentText(segment) }}</span>
          <template v-else>{{ segment.text }}</template>
          <button
            v-for="issue in segment.endingIssues"
            :key="issue.issue_id"
            type="button"
            class="document-highlight-control"
            :class="{
              'document-highlight-control--active': issue.issue_id === selectedIssueId
            }"
            :data-highlight-issue-id="issue.issue_id"
            :aria-label="`选择问题：${issue.original || issue.message}`"
            :aria-current="issue.issue_id === selectedIssueId ? 'true' : 'false'"
            :title="issue.message"
            @click="emit('selectHighlight', issue.issue_id)"
          />
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
  overflow: auto;
  background: #edf1f7;
  border: 1px solid #dfe5ef;
  border-radius: 16px;
}

.document-viewer__heading {
  position: sticky;
  z-index: 2;
  top: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 13px 18px;
  background: rgba(255, 255, 255, 0.95);
  border-bottom: 1px solid #dfe5ef;
  backdrop-filter: blur(8px);
}

.document-viewer__heading p {
  margin: 0 0 2px;
  color: #667085;
  font-size: 0.72rem;
}

.document-viewer__heading strong,
.document-viewer__heading span {
  color: #30394d;
  font-size: 0.8rem;
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
  background: #fff0a8;
  border-radius: 2px;
}

.document-highlight-range--active {
  background: #ffd56a;
  outline: 2px solid #bd7d18;
  outline-offset: 1px;
}

.document-highlight-control {
  display: inline-grid;
  width: 0.82em;
  height: 0.82em;
  margin: 0 0.12em;
  padding: 0;
  place-items: center;
  vertical-align: super;
  background: #d99425;
  border: 2px solid #fff;
  border-radius: 50%;
  box-shadow: 0 0 0 1px #bd7d18;
  cursor: pointer;
}

.document-highlight-control:hover,
.document-highlight-control:focus-visible,
.document-highlight-control--active {
  background: #8054d6;
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
