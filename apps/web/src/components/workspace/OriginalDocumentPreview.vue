<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { fetchReviewLayout, type ReviewLayout } from '../../api/originalPreview'
import type { SearchMatch } from '../../composables/useSearchReplace'
import type { IssueState } from '../../types/verification'
import type { DocumentIssue } from '../../utils/documentPresentation'
import { layoutRectangles } from '../../utils/layoutPresentation'
import { revealWithinPane } from '../../utils/revealWithinPane'
import ReviewLayoutPage from './ReviewLayoutPage.vue'
import { vSelectMenu } from '../../directives/selectMenu'

const props = withDefaults(defineProps<{
  jobId: string
  sourceVersion: string
  text: string
  issues: readonly DocumentIssue[]
  issueStates: Readonly<Record<string, IssueState>>
  selectedIssueId: string | null
  revealKey?: string
  navigationTarget?: 'issue' | 'search'
  searchMatches?: readonly SearchMatch[]
  activeSearchMatchIndex?: number
  toolbarTarget?: HTMLElement | null
}>(), { searchMatches: () => [], activeSearchMatchIndex: -1, navigationTarget: 'issue' })
const emit = defineEmits<{ 'select-issue': [issueId: string] }>()
const layout = ref<ReviewLayout | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const root = ref<HTMLElement | null>(null)
const zoom = ref<number | 'fit'>('fit')
let controller: AbortController | null = null
let generation = 0
let running = false
let pending = false
let disposed = false

const pages = computed(() => layout.value?.pages ?? [])
const missingLocation = computed(() => {
  if (loading.value || error.value || !layout.value) return false
  const issue = props.issues.find((item) => item.issue_id === props.selectedIssueId)
  return !!issue && !pages.value.some((page) =>
    layoutRectangles(page, issue.start, issue.end).length > 0
  )
})

async function load(): Promise<void> {
  if (running) {
    pending = true
    return
  }
  running = true
  pending = false
  loading.value = true
  error.value = null
  const requestGeneration = generation
  const request = new AbortController()
  controller = request
  try {
    const rendered = await fetchReviewLayout(
      props.jobId, props.sourceVersion, props.text, request.signal
    )
    if (!disposed && requestGeneration === generation) layout.value = rendered
  } catch (caught) {
    if (!disposed && requestGeneration === generation) {
      error.value = caught instanceof Error ? caught.message : '无法加载文档版式。'
    }
  } finally {
    running = false
    if (!disposed) {
      if (pending) void load()
      else loading.value = false
    }
  }
}

async function revealSelection(): Promise<void> {
  await nextTick()
  if (loading.value || error.value) return
  const search = root.value?.querySelector<HTMLElement>(
    `[data-search-match="${props.activeSearchMatchIndex}"]`
  )
  const issue = Array.from(root.value?.querySelectorAll<HTMLElement>('[data-issue-id]') ?? [])
    .find((element) => element.dataset.issueId === props.selectedIssueId)
  const target = props.navigationTarget === 'search' ? search : issue
  if (target) {
    revealWithinPane(
      target, root.value?.querySelector<HTMLElement>('.layout-scroll') ?? null,
      true, props.navigationTarget === 'issue' ? 'center' : 'nearest'
    )
  }
}

watch(() => [props.jobId, props.sourceVersion, props.text], (current, previous) => {
  generation += 1
  loading.value = true
  if (previous && (current[0] !== previous[0] || current[1] !== previous[1])) layout.value = null
  void load()
}, { immediate: true })
watch(() => [
  layout.value, loading.value, props.selectedIssueId, props.revealKey,
  props.searchMatches, props.activeSearchMatchIndex, props.navigationTarget, zoom.value
], revealSelection, { flush: 'post' })
onBeforeUnmount(() => {
  disposed = true
  controller?.abort()
})
</script>

<template>
  <section ref="root" class="original-preview" aria-label="文档版式审阅" :aria-busy="loading">
    <Teleport :to="toolbarTarget || 'body'" :disabled="!toolbarTarget">
    <div class="layout-toolbar" :class="{ 'is-inline': toolbarTarget }">
      <span>{{ pages.length ? `${pages.length} 页` : '文档版式' }}</span>
      <span v-if="loading" role="status">正在更新文档版式…</span>
      <span v-else-if="layout?.revision_applied && !error" role="status">已显示当前修订</span>
      <label>缩放
        <select v-select-menu class="ui-field" v-model.number="zoom" aria-label="文档缩放">
          <option value="fit">适合宽度</option>
          <option :value="25">25%</option>
          <option :value="50">50%</option>
          <option :value="75">75%</option>
          <option :value="100">100%</option>
          <option :value="125">125%</option>
          <option :value="150">150%</option>
          <option :value="200">200%</option>
        </select>
      </label>
    </div>
    </Teleport>
    <p v-if="layout?.notice && !loading && !error" class="preview-note" role="status">{{ layout.notice }}</p>
    <p v-if="missingLocation" class="preview-note" data-location-warning role="status">
      此问题无法精确定位到原版式，请结合右侧原文和上下文处理。
    </p>
    <div v-if="error" class="preview-state" role="alert">
      <p>{{ error }} 当前修订仍保留；下方如有页面，是上次成功的预览。</p>
      <button class="ui-button" type="button" data-retry-preview @click="load">重试预览</button>
    </div>
    <div class="layout-scroll" tabindex="0" aria-label="文档页面">
      <div class="layout-pages" :style="{ width: `${zoom === 'fit' ? 100 : zoom}%` }">
        <ReviewLayoutPage v-for="(page, pageIndex) in pages" :key="pageIndex"
          :page="page" :page-index="pageIndex" :issues="issues" :issue-states="issueStates"
          :selected-issue-id="selectedIssueId" :search-matches="searchMatches"
          :active-search-match-index="activeSearchMatchIndex" :disabled="loading || !!error"
          @select-issue="emit('select-issue', $event)" />
      </div>
    </div>
  </section>
</template>

<style scoped>
.original-preview { display: flex; flex-direction: column; height: 100%; min-height: 0; white-space: normal; }
.layout-toolbar { display: flex; flex-shrink: 0; flex-wrap: wrap; align-items: center; gap: 4px 12px; padding: 4px 12px; font-size: 12px; border-bottom: 1px solid var(--border); color: var(--muted); background: var(--surface); }
.layout-toolbar label { margin-left: auto; white-space: nowrap; }
.layout-toolbar select { margin-left: 6px; min-height: 32px; padding-block: 6px; }
.layout-toolbar.is-inline { padding: 0; border: 0; gap: 4px 8px; background: transparent; }
.preview-note, .preview-state { flex-shrink: 0; margin: 0; padding: 8px 12px; font-size: 12px; line-height: 1.6; color: var(--muted); border-bottom: 1px solid var(--border); }
.preview-state { color: var(--danger); background: var(--danger-soft); }
.layout-scroll { flex: 1; min-height: 0; overflow: auto; background: var(--canvas); padding: 8px; }
.layout-pages { display: flex; flex-direction: column; align-items: center; gap: 38px; margin-inline: auto; padding-bottom: 28px; }
</style>
