<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'

import type {
  IssueState,
  VerificationIssue,
  VerificationResult
} from '../../types/verification'
import { MAX_VERIFICATION_ISSUES } from '../../validation/verificationLimits'

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
  issue: VerificationIssue
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
    issues?: readonly VerificationIssue[]
    issueStates?: Readonly<Record<string, IssueState>>
    selectedIssueId: string | null
    mode?: DocumentViewMode
  }>(),
  {
    issues: undefined,
    issueStates: () => ({}),
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
  sourceIssues: readonly VerificationIssue[]
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
      end <= start ||
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
  const indexedText = indexText(props.result.text)
  const issues = validatedIssues(
    props.result.text,
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
    const ends = endingAt.get(prepared.end) ?? []
    ends.push(prepared)
    endingAt.set(prepared.end, ends)
  }

  const orderedBoundaries = [...boundaries].sort((left, right) => left - right)
  let activeCount = 0
  const collected: StructuralSourceSegment[] = []
  for (let index = 0; index < orderedBoundaries.length - 1; index += 1) {
    const start = orderedBoundaries[index]
    const end = orderedBoundaries[index + 1]
    activeCount -= endingAt.get(start)?.length ?? 0
    const startingIssues = startingAt.get(start) ?? []
    activeCount += startingIssues.length
    collected.push({
      start,
      text: indexedText.characters.slice(start, end).join(''),
      issueCount: activeCount,
      markers: startingIssues
        .map(({ issue, issueId }) => ({
          issueId,
          label: `${issue.message}：${issue.original}`,
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

function activateIssue(issueId: string): void {
  emit('select-issue', issueId)
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
  if (control && typeof control.scrollIntoView === 'function') {
    control.scrollIntoView({
      behavior:
        typeof window.matchMedia === 'function' &&
        window.matchMedia('(prefers-reduced-motion: reduce)').matches
          ? 'auto'
          : 'smooth',
      block: 'center',
      inline: 'nearest'
    })
  }
}

watch(
  () => props.selectedIssueId,
  (issueId) => {
    void scrollSelectedSource(issueId)
  },
  { flush: 'post', immediate: true }
)
</script>

<template>
  <div ref="root" class="document-viewer" :data-view-mode="mode">
    <template v-if="mode === 'sentence'">
      <ol class="line-numbers" aria-hidden="true">
        <li
          v-for="line in lines"
          :key="line.number"
          data-line-number
        >
          {{ line.number }}
        </li>
      </ol>
      <div class="source-lines" data-source-text aria-label="源文本">
        <div
          v-for="line in lines"
          :key="line.number"
          class="source-line"
          data-source-line
        >
          <template
            v-for="segment in line.segments"
            :key="segment.start"
          >
            <button
              v-for="marker in segment.markers"
              :key="marker.issueId"
              type="button"
              class="issue-marker"
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
              @click="activateIssue(marker.issueId)"
              @keydown.enter.prevent="activateIssue(marker.issueId)"
              @keydown.space.prevent="activateIssue(marker.issueId)"
            ></button>
            <span
              :class="[
                'source-segment',
                {
                  highlighted: segment.issueCount > 0,
                  overlapping: segment.issueCount > 1,
                  accepted: segment.hasAccepted,
                  rejected: segment.allRejected,
                  selected: segment.selected
                }
              ]"
              :data-issue-count="segment.issueCount || undefined"
            >{{ segment.text }}</span>
          </template>
        </div>
      </div>
    </template>

    <pre v-else class="continuous-source" data-source-text aria-label="源文本"><template
      v-for="segment in segments"
      :key="segment.start"
    ><button
      v-for="marker in segment.markers"
      :key="marker.issueId"
      type="button"
      class="issue-marker"
      :class="[
        `severity-${marker.severity}`,
        marker.state,
        { selected: selectedIssueId === marker.issueId }
      ]"
      :aria-label="marker.label"
      :aria-current="selectedIssueId === marker.issueId ? 'true' : undefined"
      :data-issue-id="marker.issueId"
      data-issue-role="source"
      @click="activateIssue(marker.issueId)"
      @keydown.enter.prevent="activateIssue(marker.issueId)"
      @keydown.space.prevent="activateIssue(marker.issueId)"
    ></button><span
      :class="[
        'source-segment',
        {
          highlighted: segment.issueCount > 0,
          overlapping: segment.issueCount > 1,
          accepted: segment.hasAccepted,
          rejected: segment.allRejected,
          selected: segment.selected
        }
      ]"
      :data-issue-count="segment.issueCount || undefined"
    >{{ segment.text }}</span></template></pre>
  </div>
</template>

<style scoped>
.document-viewer {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  min-height: 100%;
  color: var(--text);
  background: var(--surface);
  font: 15px/2 ui-monospace, SFMono-Regular, Menlo, monospace;
}

.line-numbers {
  margin: 0;
  padding: 24px 12px 24px 18px;
  list-style: none;
  color: var(--muted);
  background: var(--surface-2);
  text-align: right;
  user-select: none;
}

.line-numbers li {
  min-height: 2em;
}

.source-lines {
  min-width: 0;
  padding: 24px 28px 24px 16px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.source-line {
  display: contents;
}

.continuous-source {
  grid-column: 1 / -1;
  min-height: 100%;
  margin: 0;
  padding: 24px 28px;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}

.source-segment.highlighted {
  border-radius: 3px;
  background: #fef3c7;
}

.source-segment.overlapping {
  text-decoration: underline double #d97706;
  text-underline-offset: 3px;
}

.source-segment.selected {
  background: #bfdbfe;
  outline: 2px solid #2563eb;
  outline-offset: 1px;
}

.source-segment.accepted {
  background: #bbf7d0;
}

.source-segment.rejected {
  opacity: 0.52;
  text-decoration: line-through;
}

.issue-marker {
  width: 0.85rem;
  height: 0.85rem;
  margin: 0 0.12rem;
  padding: 0;
  vertical-align: 0.12rem;
  border: 2px solid var(--surface);
  border-radius: 999px;
  background: #f59e0b;
  box-shadow: 0 0 0 1px #b45309;
  cursor: pointer;
}

.issue-marker.severity-error {
  background: #ef4444;
  box-shadow: 0 0 0 1px #b91c1c;
}

.issue-marker.severity-info {
  background: #3b82f6;
  box-shadow: 0 0 0 1px #1d4ed8;
}

.issue-marker.selected {
  box-shadow: 0 0 0 3px #2563eb;
}

.issue-marker.accepted {
  background: #16a34a;
  box-shadow: 0 0 0 1px #15803d;
}

.issue-marker.rejected {
  opacity: 0.52;
}

.issue-marker:focus-visible {
  outline: 3px solid #2563eb;
  outline-offset: 3px;
}
</style>
