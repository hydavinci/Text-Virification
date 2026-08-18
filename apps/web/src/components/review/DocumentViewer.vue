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
  issueId: string | null
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
const sentinel = ref<Element | null>(null)
let observer: ReviewIntersectionObserver | null = null
let requestedCursor: string | null = null

function issuesForBlock(blockId: string): Issue[] {
  return props.issues.filter((issue) => issue.block_id === blockId)
}

function segmentsForBlock(block: DocumentBlock): TextSegment[] {
  const points = Array.from(block.text)
  const issues = issuesForBlock(block.block_id).sort(
    (left, right) => left.start - right.start || left.end - right.end
  )

  if (!issues.length) {
    return [{ key: `${block.block_id}-text`, text: block.text, issueId: null }]
  }

  const segments: TextSegment[] = []
  let cursor = 0

  for (const issue of issues) {
    const start = Math.max(0, Math.min(points.length, issue.start))
    const end = Math.max(start, Math.min(points.length, issue.end))

    if (end <= cursor || start < cursor) {
      continue
    }
    if (start > cursor) {
      segments.push({
        key: `${block.block_id}-text-${cursor}`,
        text: points.slice(cursor, start).join(''),
        issueId: null
      })
    }
    if (end > start) {
      segments.push({
        key: issue.issue_id,
        text: points.slice(start, end).join(''),
        issueId: issue.issue_id
      })
    }
    cursor = end
  }

  if (cursor < points.length) {
    segments.push({
      key: `${block.block_id}-text-${cursor}`,
      text: points.slice(cursor).join(''),
      issueId: null
    })
  }

  return segments
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
  () => props.selectedIssueId,
  async (issueId) => {
    if (!issueId) {
      return
    }
    await nextTick()
    const highlight = Array.from(
      document.querySelectorAll<HTMLElement>('[data-highlight-issue-id]')
    ).find((element) => element.dataset.highlightIssueId === issueId)
    highlight?.scrollIntoView?.({ block: 'center' })
  }
)

onBeforeUnmount(() => {
  observer?.disconnect()
})
</script>

<template>
  <article class="document-viewer" aria-label="文档内容">
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
        <template v-for="segment in segmentsForBlock(block)" :key="segment.key">
          <button
            v-if="segment.issueId"
            type="button"
            class="document-highlight"
            :class="{ 'document-highlight--active': segment.issueId === selectedIssueId }"
            :data-highlight-issue-id="segment.issueId"
            :aria-current="segment.issueId === selectedIssueId ? 'true' : 'false'"
            @click="emit('selectHighlight', segment.issueId)"
          >
            {{ segment.text }}
          </button>
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

.document-highlight {
  display: inline;
  margin: 0;
  padding: 1px 0;
  color: inherit;
  font: inherit;
  line-height: inherit;
  background: #fff0a8;
  border: 0;
  border-radius: 2px;
  cursor: pointer;
}

.document-highlight:hover,
.document-highlight:focus-visible,
.document-highlight--active {
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
