import {
  computed,
  ref,
  toValue,
  watch,
  type MaybeRefOrGetter
} from 'vue'

import type {
  IssueSeverity,
  VerificationIssue
} from '../types/verification'

export type IssueLayerFilter = 'all' | string
export type IssueSeverityFilter = 'all' | IssueSeverity

interface UseIssueNavigationOptions {
  issues: MaybeRefOrGetter<readonly VerificationIssue[]>
}

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

export function useIssueNavigation({
  issues
}: UseIssueNavigationOptions) {
  const selectedIssueId = ref<string | null>(null)
  const selectedLayer = ref<IssueLayerFilter>('all')
  const selectedSeverity = ref<IssueSeverityFilter>('all')

  const orderedIssues = computed<readonly VerificationIssue[]>(() =>
    [...toValue(issues)].sort(compareIssues)
  )

  const visibleIssues = computed<readonly VerificationIssue[]>(() =>
    orderedIssues.value.filter(
      (issue) =>
        (selectedLayer.value === 'all' ||
          issue.layer === selectedLayer.value) &&
        (selectedSeverity.value === 'all' ||
          issue.severity === selectedSeverity.value)
    )
  )

  const selectedIssue = computed(
    () =>
      visibleIssues.value.find(
        (issue) => issue.issue_id === selectedIssueId.value
      ) ?? null
  )

  function selectIssue(issueId: string): void {
    const issue = visibleIssues.value.find(
      (candidate) => candidate.issue_id === issueId
    )
    selectedIssueId.value = issue?.issue_id ?? null
  }

  function selectOffset(offset: number): void {
    if (!Number.isInteger(offset) || offset < 0) {
      selectedIssueId.value = null
      return
    }
    const issue =
      visibleIssues.value
        .filter(
          (candidate) =>
            candidate.start <= offset && offset < candidate.end
        )
        .sort(
          (left, right) =>
            left.end - left.start - (right.end - right.start) ||
            compareIssues(left, right)
        )[0] ?? null
    selectedIssueId.value = issue?.issue_id ?? null
  }

  watch(
    visibleIssues,
    (nextVisible) => {
      const currentId = selectedIssueId.value
      if (
        currentId === null ||
        nextVisible.some((issue) => issue.issue_id === currentId)
      ) {
        return
      }

      const priorIndex = orderedIssues.value.findIndex(
        (issue) => issue.issue_id === currentId
      )
      const nextIds = new Set(nextVisible.map((issue) => issue.issue_id))
      const later = orderedIssues.value
        .slice(Math.max(priorIndex + 1, 0))
        .find((issue) => nextIds.has(issue.issue_id))
      const earlier = orderedIssues.value
        .slice(0, Math.max(priorIndex, 0))
        .reverse()
        .find((issue) => nextIds.has(issue.issue_id))
      selectedIssueId.value =
        later?.issue_id ?? earlier?.issue_id ?? nextVisible[0]?.issue_id ?? null
    },
    { flush: 'sync' }
  )

  return {
    selectedIssueId,
    selectedIssue,
    selectedLayer,
    selectedSeverity,
    visibleIssues,
    selectIssue,
    selectOffset
  }
}
