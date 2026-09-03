<script setup lang="ts">
import { computed, ref, watch } from 'vue'

import type {
  IssueState,
  VerificationIssue,
  VerificationResult
} from '../../types/verification'

type DocumentViewMode = 'sentence' | 'continuous'

interface SourceMarker {
  issueId: string
  label: string
  severity: VerificationIssue['severity']
  state: IssueState
}

interface SourceSegment {
  start: number
  text: string
  coveringIssueIds: readonly string[]
  coveringStates: readonly IssueState[]
  markers: readonly SourceMarker[]
}

interface SourceLine {
  number: number
  segments: readonly SourceSegment[]
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

function compareIssues(
  left: VerificationIssue,
  right: VerificationIssue
): number {
  return (
    left.start - right.start ||
    left.end - right.end ||
    left.issue_id.localeCompare(right.issue_id)
  )
}

function validatedIssues(
  textCharacters: readonly string[]
): readonly VerificationIssue[] {
  return [...(props.issues ?? props.result.issues)]
    .filter(
      (issue) =>
        Number.isInteger(issue.start) &&
        Number.isInteger(issue.end) &&
        issue.start >= 0 &&
        issue.end > issue.start &&
        issue.end <= textCharacters.length &&
        textCharacters.slice(issue.start, issue.end).join('') ===
          issue.original
    )
    .sort(compareIssues)
}

const segments = computed<readonly SourceSegment[]>(() => {
  const characters = Array.from(props.result.text)
  const issues = validatedIssues(characters)
  const boundaries = new Set<number>([0, characters.length])
  for (let index = 0; index < characters.length; index += 1) {
    if (characters[index] === '\n') {
      boundaries.add(index)
      boundaries.add(index + 1)
    }
  }
  for (const issue of issues) {
    boundaries.add(issue.start)
    boundaries.add(issue.end)
  }

  const orderedBoundaries = [...boundaries].sort((left, right) => left - right)
  return orderedBoundaries.slice(0, -1).map((start, index) => {
    const end = orderedBoundaries[index + 1]
    const coveringIssues = issues.filter(
      (issue) => issue.start < end && start < issue.end
    )
    return {
      start,
      text: characters.slice(start, end).join(''),
      coveringIssueIds: coveringIssues.map((issue) => issue.issue_id),
      coveringStates: coveringIssues.map(
        (issue) => props.issueStates[issue.issue_id] ?? 'pending'
      ),
      markers: issues
        .filter((issue) => issue.start === start)
        .map((issue) => ({
          issueId: issue.issue_id,
          label: `${issue.message}：${issue.original}`,
          severity: issue.severity,
          state: props.issueStates[issue.issue_id] ?? 'pending'
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

function scrollSelectedSource(issueId: string | null): void {
  if (issueId === null) {
    return
  }
  const control = Array.from(
    root.value?.querySelectorAll<HTMLElement>('[data-issue-id]') ?? []
  ).find((element) => element.dataset.issueId === issueId)
  if (control && typeof control.scrollIntoView === 'function') {
    control.scrollIntoView({
      behavior: 'smooth',
      block: 'center',
      inline: 'nearest'
    })
  }
}

watch(
  () => props.selectedIssueId,
  (issueId) => {
    scrollSelectedSource(issueId)
  },
  { flush: 'post' }
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
                  highlighted: segment.coveringIssueIds.length > 0,
                  overlapping: segment.coveringIssueIds.length > 1,
                  accepted: segment.coveringStates.includes('accepted'),
                  rejected:
                    segment.coveringStates.length > 0 &&
                    segment.coveringStates.every(
                      (state) => state === 'rejected'
                    ),
                  selected: segment.coveringIssueIds.includes(
                    selectedIssueId ?? ''
                  )
                }
              ]"
              :data-issue-count="segment.coveringIssueIds.length || undefined"
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
          highlighted: segment.coveringIssueIds.length > 0,
          overlapping: segment.coveringIssueIds.length > 1,
          accepted: segment.coveringStates.includes('accepted'),
          rejected:
            segment.coveringStates.length > 0 &&
            segment.coveringStates.every((state) => state === 'rejected'),
          selected: segment.coveringIssueIds.includes(selectedIssueId ?? '')
        }
      ]"
      :data-issue-count="segment.coveringIssueIds.length || undefined"
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
