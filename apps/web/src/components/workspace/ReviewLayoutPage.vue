<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

import type { ReviewLayout } from '../../api/originalPreview'
import type { SearchMatch } from '../../composables/useSearchReplace'
import type { IssueState } from '../../types/verification'
import type { DocumentIssue } from '../../utils/documentPresentation'
import { layoutRectangles, rectangleStyle } from '../../utils/layoutPresentation'

const props = defineProps<{
  page: ReviewLayout['pages'][number]
  pageIndex: number
  issues: readonly DocumentIssue[]
  issueStates: Readonly<Record<string, IssueState>>
  selectedIssueId: string | null
  searchMatches: readonly SearchMatch[]
  activeSearchMatchIndex: number
  disabled: boolean
}>()
const emit = defineEmits<{ 'select-issue': [issueId: string] }>()
const root = ref<HTMLElement | null>(null)
const visible = ref(props.pageIndex === 0)
let observer: IntersectionObserver | null = null

const active = computed(() => {
  if (props.disabled) return false
  if (visible.value) return true
  const issue = props.issues.find((item) => item.issue_id === props.selectedIssueId)
  if (issue && layoutRectangles(props.page, issue.start, issue.end).length) return true
  const match = props.searchMatches[props.activeSearchMatchIndex]
  return !!match && layoutRectangles(props.page, match.start, match.end).length > 0
})
const marks = computed(() => !active.value ? [] : props.issues.flatMap((issue) =>
  layoutRectangles(props.page, issue.start, issue.end).map((rectangle) => ({ issue, rectangle }))
))
const matches = computed(() => !active.value ? [] : props.searchMatches.flatMap((match, index) =>
  layoutRectangles(props.page, match.start, match.end).map((rectangle) => ({ index, rectangle }))
))

onMounted(() => {
  if (typeof IntersectionObserver === 'undefined') {
    visible.value = true
    return
  }
  observer = new IntersectionObserver((entries) => {
    visible.value = entries.some((entry) => entry.isIntersecting)
  }, { root: root.value?.closest('.layout-scroll'), rootMargin: '600px' })
  if (root.value) observer.observe(root.value)
})
onBeforeUnmount(() => observer?.disconnect())
</script>

<template>
  <figure ref="root" class="layout-page"
    :style="{ aspectRatio: `${page.width} / ${page.height}` }" :data-page="pageIndex + 1">
    <img :src="page.image" :alt="`第 ${pageIndex + 1} 页：${page.text || '原始图像'}`"
      :width="page.width" :height="page.height" loading="lazy" decoding="async" draggable="false" />
    <button v-for="(mark, index) in marks" :key="`${mark.issue.issue_id}-${index}`"
      type="button" class="layout-issue" :class="[
        mark.issue.severity, issueStates[mark.issue.issue_id] ?? 'pending',
        { selected: mark.issue.issue_id === selectedIssueId }
      ]"
      :style="rectangleStyle(mark.rectangle, page)"
      :aria-label="`${mark.issue.original || '删除位置'}：${mark.issue.message}`"
      :aria-current="mark.issue.issue_id === selectedIssueId ? 'true' : undefined"
      :title="mark.issue.message" :data-issue-id="mark.issue.issue_id" data-issue-role="source"
      @click="emit('select-issue', mark.issue.issue_id)" />
    <span v-for="(match, index) in matches" :key="`search-${index}`"
      class="layout-search" :class="{ active: match.index === activeSearchMatchIndex }"
      :style="rectangleStyle(match.rectangle, page)" :data-search-match="match.index" />
    <figcaption>第 {{ pageIndex + 1 }} 页</figcaption>
  </figure>
</template>

<style scoped>
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
</style>
