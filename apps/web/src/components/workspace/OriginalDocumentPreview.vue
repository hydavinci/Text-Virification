<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { fetchReviewLayout, type ReviewLayout } from '../../api/originalPreview'
import type { SearchMatch } from '../../composables/useSearchReplace'
import type { IssueState } from '../../types/verification'
import type { DocumentIssue } from '../../utils/documentPresentation'
import { layoutRectangles, rectangleStyle } from '../../utils/layoutPresentation'
import { revealWithinPane } from '../../utils/revealWithinPane'

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

const pages = computed(() => (layout.value?.pages ?? []).map((page) => ({
  ...page,
  marks: loading.value || error.value ? [] : props.issues.flatMap((issue) =>
    layoutRectangles(page, issue.start, issue.end).map((rectangle) => ({ issue, rectangle }))
  ),
  matches: loading.value || error.value ? [] : props.searchMatches.flatMap((match, index) =>
    layoutRectangles(page, match.start, match.end).map((rectangle) => ({ index, rectangle }))
  )
})))
const missingLocation = computed(() => !loading.value && !error.value && layout.value &&
  props.selectedIssueId !== null && props.issues.some((issue) => issue.issue_id === props.selectedIssueId) &&
  !pages.value.some((page) => page.marks.some((mark) => mark.issue.issue_id === props.selectedIssueId))
)

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
    revealWithinPane(target, root.value?.querySelector<HTMLElement>('.layout-scroll') ?? null, true)
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
    <div class="layout-toolbar">
      <span>{{ pages.length ? `${pages.length} 页` : '文档版式' }}</span>
      <span v-if="loading" role="status">正在更新文档版式…</span>
      <span v-else-if="layout?.revision_applied && !error" role="status">已显示当前修订</span>
      <label>缩放
        <select class="ui-field" v-model.number="zoom" aria-label="文档缩放">
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
        <figure v-for="(page, pageIndex) in pages" :key="pageIndex" class="layout-page"
          :style="{ aspectRatio: `${page.width} / ${page.height}` }"
          :data-page="pageIndex + 1">
          <img :src="page.image" :alt="`第 ${pageIndex + 1} 页：${page.text || '原始图像'}`"
            :width="page.width" :height="page.height" draggable="false" />
          <button v-for="(mark, index) in page.marks" :key="`${mark.issue.issue_id}-${index}`"
            type="button" class="layout-issue" :class="[
              mark.issue.severity, issueStates[mark.issue.issue_id] ?? 'pending',
              { selected: mark.issue.issue_id === selectedIssueId }
            ]"
            :style="rectangleStyle(mark.rectangle, page)"
            :aria-label="`${mark.issue.original || '删除位置'}：${mark.issue.message}`"
            :aria-current="mark.issue.issue_id === selectedIssueId ? 'true' : undefined"
            :title="mark.issue.message" :data-issue-id="mark.issue.issue_id" data-issue-role="source"
            @click="emit('select-issue', mark.issue.issue_id)" />
          <span v-for="(match, index) in page.matches" :key="`search-${index}`"
            class="layout-search" :class="{ active: match.index === activeSearchMatchIndex }"
            :style="rectangleStyle(match.rectangle, page)" :data-search-match="match.index" />
          <figcaption>第 {{ pageIndex + 1 }} 页</figcaption>
        </figure>
      </div>
    </div>
  </section>
</template>

<style scoped>
.original-preview { display: flex; flex-direction: column; height: 100%; min-height: 0; white-space: normal; }
.layout-toolbar { display: flex; flex-shrink: 0; flex-wrap: wrap; align-items: center; gap: 8px 12px; padding: 8px 16px; font-size: 12px; border-bottom: 1px solid var(--border); color: var(--muted); background: var(--surface); }
.layout-toolbar label { margin-left: auto; white-space: nowrap; }
.layout-toolbar select { margin-left: 6px; min-height: 32px; padding-block: 6px; }
.preview-note, .preview-state { flex-shrink: 0; margin: 0; padding: 8px 12px; font-size: 12px; line-height: 1.6; color: var(--muted); border-bottom: 1px solid var(--border); }
.preview-state { color: var(--danger); background: var(--danger-soft); }
.layout-scroll { flex: 1; min-height: 0; overflow: auto; background: var(--canvas); padding: 24px; }
.layout-pages { display: flex; flex-direction: column; align-items: center; gap: 38px; margin-inline: auto; padding-bottom: 28px; }
.layout-page { position: relative; flex: none; width: 100%; margin: 0; background: white; box-shadow: var(--shadow-paper); }
.layout-page img { display: block; width: 100%; height: 100%; }
.layout-page figcaption { position: absolute; top: 100%; width: 100%; padding: 8px; text-align: center; font-size: 12px; color: var(--muted); font-variant-numeric: tabular-nums; }
.layout-issue, .layout-search { position: absolute; border: 0; padding: 0; border-radius: 2px; }
.layout-issue { background: #f59e0b26; border-bottom: 2px solid #f59e0b; cursor: pointer; }
.layout-issue.error { background: #ef444426; border-color: #ef4444; }
.layout-issue.accepted { background: #10b98126; border-color: #10b981; }
.layout-issue.rejected { background: #64748b18; border-color: #94a3b8; }
.layout-issue.selected, .layout-issue:focus-visible { outline: 2px solid #2563eb; outline-offset: 2px; z-index: 2; }
.layout-search { pointer-events: none; background: #facc1555; outline: 1px solid #eab308; }
.layout-search.active { background: #fb923c66; outline: 2px solid #ea580c; }
@media (max-width: 760px) {
  .layout-scroll { padding: 12px; }
}
</style>
