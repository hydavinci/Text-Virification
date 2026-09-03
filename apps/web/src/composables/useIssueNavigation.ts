import {
  computed,
  nextTick,
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

function canScroll(element: Element): element is Element & {
  scrollIntoView: (options?: ScrollIntoViewOptions) => void
} {
  return (
    element instanceof HTMLElement &&
    typeof element.scrollIntoView === 'function'
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

  async function scrollSelection(issueId: string): Promise<void> {
    await nextTick()
    const matchingElements = Array.from(
      document.querySelectorAll<HTMLElement>('[data-issue-id]')
    ).filter((element) => element.dataset.issueId === issueId)
    for (const role of ['source', 'list']) {
      const element = matchingElements.find(
        (candidate) => candidate.dataset.issueRole === role
      )
      if (element && canScroll(element)) {
        element.scrollIntoView({
          behavior: 'smooth',
          block: 'center',
          inline: 'nearest'
        })
      }
    }
  }

  function selectIssue(issueId: string): void {
    const issue = visibleIssues.value.find(
      (candidate) => candidate.issue_id === issueId
    )
    selectedIssueId.value = issue?.issue_id ?? null
    if (issue) {
      void scrollSelection(issue.issue_id)
    }
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
    if (issue) {
      void scrollSelection(issue.issue_id)
    }
  }

  watch(
    visibleIssues,
    (nextVisible, previousVisible) => {
      const currentId = selectedIssueId.value
      if (
        currentId === null ||
        nextVisible.some((issue) => issue.issue_id === currentId)
      ) {
        return
      }

      const priorOrder =
        previousVisible.findIndex((issue) => issue.issue_id === currentId) >= 0
          ? previousVisible
          : orderedIssues.value
      const priorIndex = priorOrder.findIndex(
        (issue) => issue.issue_id === currentId
      )
      const nextIds = new Set(nextVisible.map((issue) => issue.issue_id))
      const later = priorOrder
        .slice(Math.max(priorIndex + 1, 0))
        .find((issue) => nextIds.has(issue.issue_id))
      const earlier = priorOrder
        .slice(0, Math.max(priorIndex, 0))
        .reverse()
        .find((issue) => nextIds.has(issue.issue_id))
      selectedIssueId.value =
        later?.issue_id ?? earlier?.issue_id ?? nextVisible[0]?.issue_id ?? null
      if (selectedIssueId.value !== null) {
        void scrollSelection(selectedIssueId.value)
      }
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
