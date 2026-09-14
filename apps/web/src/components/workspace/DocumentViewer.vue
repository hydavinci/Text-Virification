<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type {
  IssueState,
  VerificationIssue,
  VerificationResult
} from '../../types/verification'
import { MAX_VERIFICATION_ISSUES } from '../../validation/verificationLimits'
import type { SearchMatch } from '../../composables/useSearchReplace'
import type { DocumentIssue } from '../../utils/documentPresentation'
import { revealWithinPane } from '../../utils/revealWithinPane'

type DocumentViewMode = 'sentence' | 'continuous'

interface SourceMarker {
  issueId: string
  label: string
  severity: VerificationIssue['severity']
  state: IssueState
}

type StructuralSourceMarker = Omit<SourceMarker, 'state'>

interface StructuralSourceSegment {
  start: number
  text: string
  issueCount: number
  searchMatchIndex: number | null
  markers: readonly StructuralSourceMarker[]
}

interface SourceSegment extends StructuralSourceSegment {
  hasAccepted: boolean
  allRejected: boolean
  selected: boolean
  markers: readonly SourceMarker[]
}

interface SourceLine {
  number: number
  segments: readonly SourceSegment[]
}

interface IndexedText {
  characters: readonly string[]
  utf16Offsets: readonly number[]
}

interface PreparedIssue {
  issue: DocumentIssue
  issueId: string
  start: number
  end: number
}

interface SourceStructure {
  issues: readonly PreparedIssue[]
  segments: readonly StructuralSourceSegment[]
}

interface IssueStateEvent {
  state: IssueState
  selected: boolean
}

const props = withDefaults(
  defineProps<{
    result: VerificationResult
    text?: string
    issues?: readonly DocumentIssue[]
    issueStates?: Readonly<Record<string, IssueState>>
    selectedIssueId: string | null
    revealKey?: string
    mode?: DocumentViewMode
    searchMatches?: readonly SearchMatch[]
    activeSearchMatchIndex?: number
  }>(),
  {
    issues: undefined,
    issueStates: () => ({}),
    searchMatches: () => [],
    activeSearchMatchIndex: -1,
    mode: 'sentence'
  }
)

const emit = defineEmits<{
  'select-issue': [issueId: string]
}>()

const root = ref<HTMLElement | null>(null)

function comparePreparedIssues(
  left: PreparedIssue,
  right: PreparedIssue
): number {
  return (
    left.start - right.start ||
    left.end - right.end ||
    left.issueId.localeCompare(right.issueId)
  )
}

function indexText(text: string): IndexedText {
  const characters: string[] = []
  const utf16Offsets = [0]
  for (const character of text) {
    characters.push(character)
    utf16Offsets.push(
      (utf16Offsets[utf16Offsets.length - 1] ?? 0) + character.length
    )
  }
  return { characters, utf16Offsets }
}

function validatedIssues(
  text: string,
  indexedText: IndexedText,
  sourceIssues: readonly DocumentIssue[]
): readonly PreparedIssue[] {
  if (sourceIssues.length > MAX_VERIFICATION_ISSUES) {
    return []
  }
  const prepared: PreparedIssue[] = []
  for (const issue of sourceIssues) {
    const start = issue.start
    const end = issue.end
    const utf16Start = indexedText.utf16Offsets[start]
    const utf16End = indexedText.utf16Offsets[end]
    if (
      !Number.isInteger(start) ||
      !Number.isInteger(end) ||
      start < 0 ||
      end < start ||
      end > indexedText.characters.length ||
      utf16Start === undefined ||
      utf16End === undefined ||
      text.slice(utf16Start, utf16End) !== issue.original
    ) {
      continue
    }
    prepared.push({ issue, issueId: issue.issue_id, start, end })
  }
  return prepared.sort(comparePreparedIssues)
}

const sourceStructure = computed<SourceStructure>(() => {
  const text = props.text ?? props.result.text
  const indexedText = indexText(text)
  const issues = validatedIssues(
    text,
    indexedText,
    props.issues ?? props.result.issues
  )
  const boundaries = new Set<number>([
    0,
    indexedText.characters.length
  ])
  const startingAt = new Map<number, PreparedIssue[]>()
  const endingAt = new Map<number, PreparedIssue[]>()
  for (let index = 0; index < indexedText.characters.length; index += 1) {
    if (indexedText.characters[index] === '\n') {
      boundaries.add(index)
      boundaries.add(index + 1)
    }
  }
  for (const prepared of issues) {
    boundaries.add(prepared.start)
    boundaries.add(prepared.end)
    const starts = startingAt.get(prepared.start) ?? []
    starts.push(prepared)
    startingAt.set(prepared.start, starts)
    if (prepared.end > prepared.start) {
      const ends = endingAt.get(prepared.end) ?? []
      ends.push(prepared)
      endingAt.set(prepared.end, ends)
    }
  }
  const matches = props.searchMatches
    .map((match, index) => ({ ...match, index }))
    .filter(({ start, end }) =>
      Number.isInteger(start) && Number.isInteger(end) &&
      start >= 0 && end > start && end <= indexedText.characters.length
    )
  for (const match of matches) {
    boundaries.add(match.start)
    boundaries.add(match.end)
  }

  const orderedBoundaries = [...boundaries].sort((left, right) => left - right)
  let activeCount = 0
  let matchIndex = 0
  const collected: StructuralSourceSegment[] = []
  for (let index = 0; index < orderedBoundaries.length; index += 1) {
    const start = orderedBoundaries[index]
    const end = orderedBoundaries[index + 1] ?? start
    activeCount -= endingAt.get(start)?.length ?? 0
    const startingIssues = startingAt.get(start) ?? []
    if (start === end && startingIssues.length === 0) {
      continue
    }
    activeCount += startingIssues.filter((issue) => issue.end > issue.start).length
    while (matches[matchIndex] && matches[matchIndex].end <= start) {
      matchIndex += 1
    }
    const match = matches[matchIndex]
    collected.push({
      start,
      text: indexedText.characters.slice(start, end).join(''),
      issueCount: activeCount,
      searchMatchIndex: start < end && match && match.start <= start
        ? match.index : null,
      markers: startingIssues
        .map(({ issue, issueId }) => ({
          issueId,
          label: `${issue.message}：${issue.sourceOriginal ?? issue.original}`,
          severity: issue.severity
        }))
    })
  }
  return { issues, segments: collected }
})

function pushStateEvent(
  events: Map<number, IssueStateEvent[]>,
  position: number,
  event: IssueStateEvent
): void {
  const bucket = events.get(position) ?? []
  bucket.push(event)
  events.set(position, bucket)
}

function applyStateEvent(
  event: IssueStateEvent,
  delta: 1 | -1,
  counts: { accepted: number; rejected: number; selected: number }
): void {
  if (event.state === 'accepted') {
    counts.accepted += delta
  } else if (event.state === 'rejected') {
    counts.rejected += delta
  }
  if (event.selected) {
    counts.selected += delta
  }
}

const segments = computed<readonly SourceSegment[]>(() => {
  const structure = sourceStructure.value
  const startingAt = new Map<number, IssueStateEvent[]>()
  const endingAt = new Map<number, IssueStateEvent[]>()
  for (const issue of structure.issues) {
    if (issue.start === issue.end) {
      continue
    }
    const event = {
      state: props.issueStates[issue.issueId] ?? 'pending',
      selected: props.selectedIssueId === issue.issueId
    }
    pushStateEvent(startingAt, issue.start, event)
    pushStateEvent(endingAt, issue.end, event)
  }

  const active = { accepted: 0, rejected: 0, selected: 0 }
  return structure.segments.map((segment) => {
    for (const event of endingAt.get(segment.start) ?? []) {
      applyStateEvent(event, -1, active)
    }
    for (const event of startingAt.get(segment.start) ?? []) {
      applyStateEvent(event, 1, active)
    }
    return {
      ...segment,
      hasAccepted: active.accepted > 0,
      allRejected:
        segment.issueCount > 0 && active.rejected === segment.issueCount,
      selected: active.selected > 0,
      markers: segment.markers.map((marker) => ({
        ...marker,
        state: props.issueStates[marker.issueId] ?? 'pending'
      }))
    }
  })
})

const lines = computed<readonly SourceLine[]>(() => {
  const collected: SourceSegment[][] = [[]]
  for (const segment of segments.value) {
    collected[collected.length - 1].push(segment)
    if (segment.text === '\n') {
      collected.push([])
    }
  }
  return collected.map((lineSegments, index) => ({
    number: index + 1,
    segments: lineSegments
  }))
})

function activateSegment(segment: SourceSegment, fromPointer = false): void {
  if (fromPointer && window.getSelection()?.isCollapsed === false) {
    return
  }
  const issues = sourceStructure.value.issues.filter(
    (issue) => issue.start <= segment.start && issue.end > segment.start
  )
  if (issues.length > 0) {
    const selectedIndex = issues.findIndex(
      (issue) => issue.issueId === props.selectedIssueId
    )
    emit('select-issue', issues[(selectedIndex + 1) % issues.length].issueId)
  }
}

async function scrollSelectedSource(issueId: string | null): Promise<void> {
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
      element.dataset.issueRole === 'source'
  )
  if (control) {
    revealWithinPane(
      control, root.value?.closest<HTMLElement>('.document-content') ?? null, false, 'center'
    )
  }
}

watch(
  () => [props.selectedIssueId, props.revealKey, props.mode] as const,
  ([issueId]) => {
    void scrollSelectedSource(issueId)
  },
  { flush: 'post', immediate: true }
)

watch(
  () => [props.searchMatches, props.activeSearchMatchIndex, props.revealKey, props.mode] as const,
  async ([matches, index]) => {
    if (!matches[index]) {
      return
    }
    await nextTick()
    if (matches !== props.searchMatches || index !== props.activeSearchMatchIndex) {
      return
    }
    const match = root.value?.querySelector<HTMLElement>(`[data-search-match="${index}"]`)
    if (match) {
      revealWithinPane(match, root.value?.closest<HTMLElement>('.document-content') ?? null)
    }
  },
  { flush: 'post', immediate: true }
)
</script>

<template>
  <div ref="root" class="document-viewer" :data-view-mode="mode">
    <template v-if="mode === 'sentence'">
      <article class="source-lines" data-source-text aria-label="文档正文">
        <div
          v-for="line in lines"
          :key="line.number"
          class="source-line"
          data-source-line
          data-source-paragraph
        >
          <template
            v-for="segment in line.segments"
            :key="segment.start"
          >
            <span
              v-for="marker in segment.markers"
              :key="marker.issueId"
              class="issue-anchor"
              aria-hidden="true"
              :class="[
                `severity-${marker.severity}`,
                marker.state,
                { selected: selectedIssueId === marker.issueId }
              ]"
              :aria-label="marker.label"
              :aria-current="
                selectedIssueId === marker.issueId ? 'true' : undefined
              "
              :data-issue-id="marker.issueId"
              data-issue-role="source"
            ></span>
            <span
              :class="[
                'source-segment',
                {
                  highlighted: segment.issueCount > 0,
                  overlapping: segment.issueCount > 1,
                  accepted: segment.hasAccepted,
                  rejected: segment.allRejected,
                  selected: segment.selected,
                  'source-break': segment.text === '\n',
                  'search-match': segment.searchMatchIndex !== null,
                  'active-search-match': segment.searchMatchIndex !== null &&
                    segment.searchMatchIndex === activeSearchMatchIndex
                }
              ]"
              :data-issue-count="segment.issueCount || undefined"
              :data-search-match="segment.searchMatchIndex ?? undefined"
              :role="segment.issueCount > 0 ? 'button' : undefined"
              :tabindex="segment.issueCount > 0 ? 0 : undefined"
              :aria-current="segment.selected ? 'true' : undefined"
              :aria-label="segment.issueCount > 1 ? `此处有 ${segment.issueCount} 个问题，点击切换` : undefined"
              @click="activateSegment(segment, true)"
              @keydown.enter.prevent="activateSegment(segment)"
              @keydown.space.prevent="activateSegment(segment)"
            >{{ segment.text }}</span>
          </template>
        </div>
      </article>
    </template>

    <pre v-else class="continuous-source" data-source-text aria-label="文档正文"><template
      v-for="segment in segments"
      :key="segment.start"
    ><span
      v-for="marker in segment.markers"
      :key="marker.issueId"
      class="issue-anchor"
      aria-hidden="true"
      :class="[
        `severity-${marker.severity}`,
        marker.state,
        { selected: selectedIssueId === marker.issueId }
      ]"
      :aria-label="marker.label"
      :aria-current="selectedIssueId === marker.issueId ? 'true' : undefined"
      :data-issue-id="marker.issueId"
      data-issue-role="source"
    ></span><span
      :class="[
        'source-segment',
        {
          highlighted: segment.issueCount > 0,
          overlapping: segment.issueCount > 1,
          accepted: segment.hasAccepted,
          rejected: segment.allRejected,
          selected: segment.selected,
          'search-match': segment.searchMatchIndex !== null,
          'active-search-match': segment.searchMatchIndex !== null &&
            segment.searchMatchIndex === activeSearchMatchIndex
        }
      ]"
      :data-issue-count="segment.issueCount || undefined"
      :data-search-match="segment.searchMatchIndex ?? undefined"
      :role="segment.issueCount > 0 ? 'button' : undefined"
      :tabindex="segment.issueCount > 0 ? 0 : undefined"
      :aria-current="segment.selected ? 'true' : undefined"
      :aria-label="segment.issueCount > 1 ? `此处有 ${segment.issueCount} 个问题，点击切换` : undefined"
      @click="activateSegment(segment, true)"
      @keydown.enter.prevent="activateSegment(segment)"
      @keydown.space.prevent="activateSegment(segment)"
    >{{ segment.text }}</span></template></pre>
  </div>
</template>

<style scoped>
.document-viewer {
  position: relative;
  display: grid;
  min-height: 100%;
  padding: 20px;
  color: var(--text);
  background: var(--canvas);
  font-family: inherit;
  font-size: 16px;
  line-height: 1.9;
}

.source-lines,
.continuous-source {
  width: 100%;
  max-width: 52rem;
  min-width: 0;
  min-height: 100%;
  margin: 0 auto;
  padding: 32px clamp(20px, 3vw, 40px);
  border: 1px solid var(--border);
  background: var(--surface);
  box-shadow: var(--shadow-paper);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}
@media (max-width: 760px) {
  .document-viewer { padding: 10px; }
  .source-lines, .continuous-source { padding: 24px 18px; }
}

.source-line {
  min-height: 1.9em;
}

.source-line + .source-line {
  margin-top: 0.85em;
}

/* Block layout provides the line break; keep the original newline in the text. */
.source-break {
  white-space: normal;
}

.continuous-source {
  min-height: 100%;
  font: inherit;
}

.source-segment.highlighted {
  border-radius: 3px;
  color: #713f12;
  background: #fef3c7;
  cursor: pointer;
}

.source-segment:focus-visible {
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}

.source-segment.overlapping {
  text-decoration: underline double #d97706;
  text-underline-offset: 3px;
}

.source-segment.selected {
  color: #1e3a8a;
  background: #bfdbfe;
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}

.source-segment.accepted {
  color: #14532d;
  background: #bbf7d0;
}

.source-segment.rejected {
  opacity: 0.52;
  text-decoration: line-through;
}

.source-segment.search-match {
  color: #713f12;
  background: #fef08a;
  opacity: 1;
  text-decoration: none;
}

.source-segment.active-search-match {
  color: #431407;
  background: #fdba74;
  outline: 2px solid #ea580c;
  outline-offset: 1px;
  border-radius: 2px;
}

.issue-anchor {
  position: absolute;
  width: 0;
  height: 1em;
  pointer-events: none;
}
</style>
