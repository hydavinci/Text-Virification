import { mount } from '@vue/test-utils'
import { nextTick, ref } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import IssueDetails from '../src/components/workspace/IssueDetails.vue'
import IssueList from '../src/components/workspace/IssueList.vue'
import { useIssueNavigation } from '../src/composables/useIssueNavigation'
import type { IssueState, VerificationIssue } from '../src/types/verification'

function buildIssue(
  issueId: string,
  start: number,
  end: number,
  overrides: Partial<VerificationIssue> = {}
): VerificationIssue {
  return {
    issue_id: issueId,
    document_id: '11111111-1111-1111-1111-111111111111',
    verification_run_id: '22222222-2222-2222-2222-222222222222',
    block_id: 'p-0',
    page: null,
    start,
    end,
    block_start: start,
    block_end: end,
    type: 'typo',
    severity: 'warning',
    original: '原文',
    suggestion: '建议',
    alternatives: ['备选一', '备选二'],
    layer: 'character',
    message: '疑似错别字',
    description: '疑似错别字',
    rule_id: 'cn_typo',
    rule_version: '1',
    source: 'test',
    source_version: '1',
    confidence: 0.8,
    auto_fixable: true,
    context: '上下文',
    position: 99,
    end_position: 100,
    review: null,
    review_reason: null,
    ...overrides
  }
}

describe('useIssueNavigation', () => {
  let scrollIntoView: ReturnType<typeof vi.fn>

  beforeEach(() => {
    scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView
    })
  })

  afterEach(() => {
    document.body.replaceChildren()
    vi.restoreAllMocks()
  })

  it('selects offsets with half-open bounds and the most specific overlap first', () => {
    const broad = buildIssue('broad', 1, 6)
    const narrowB = buildIssue('narrow-b', 2, 4)
    const narrowA = buildIssue('narrow-a', 2, 4)
    const issues = ref<readonly VerificationIssue[]>([
      broad,
      narrowB,
      narrowA
    ])
    const navigation = useIssueNavigation({ issues })

    navigation.selectOffset(2)
    expect(navigation.selectedIssueId.value).toBe('narrow-a')

    navigation.selectOffset(4)
    expect(navigation.selectedIssueId.value).toBe('broad')

    navigation.selectOffset(6)
    expect(navigation.selectedIssueId.value).toBeNull()
  })

  it('composes severity and layer filters without mutating canonical issues', () => {
    const source = Object.freeze([
      Object.freeze(buildIssue('warning-character', 0, 1)),
      Object.freeze(
        buildIssue('error-character', 1, 2, { severity: 'error' })
      ),
      Object.freeze(
        buildIssue('error-security', 2, 3, {
          severity: 'error',
          layer: 'security'
        })
      )
    ])
    const issues = ref<readonly VerificationIssue[]>(source)
    const navigation = useIssueNavigation({ issues })

    navigation.selectedSeverity.value = 'error'
    navigation.selectedLayer.value = 'character'

    expect(navigation.visibleIssues.value.map((issue) => issue.issue_id)).toEqual([
      'error-character'
    ])
    expect(issues.value).toBe(source)
    expect(Object.isFrozen(issues.value)).toBe(true)
  })

  it('keeps a visible selection and otherwise selects the next canonical issue', async () => {
    const first = buildIssue('first', 0, 1, { severity: 'warning' })
    const selected = buildIssue('selected', 1, 2, { severity: 'warning' })
    const next = buildIssue('next', 2, 3, { severity: 'error' })
    const navigation = useIssueNavigation({
      issues: ref<readonly VerificationIssue[]>([first, selected, next])
    })

    navigation.selectIssue(selected.issue_id)
    navigation.selectedSeverity.value = 'error'
    await nextTick()
    expect(navigation.selectedIssueId.value).toBe(next.issue_id)

    navigation.selectedLayer.value = 'security'
    await nextTick()
    expect(navigation.selectedIssueId.value).toBeNull()
  })

  it('does not query or scroll global document controls after selecting a stable id', async () => {
    const issue = buildIssue('scroll-me', 0, 1)
    const querySelectorAll = vi.spyOn(document, 'querySelectorAll')
    const navigation = useIssueNavigation({
      issues: ref<readonly VerificationIssue[]>([issue])
    })

    navigation.selectIssue(issue.issue_id)
    await nextTick()

    expect(querySelectorAll).not.toHaveBeenCalled()
    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('uses full canonical order when filter eligibility changes', async () => {
    const early = buildIssue('early', 0, 1, { severity: 'error' })
    const selected = buildIssue('selected', 1, 2, { severity: 'error' })
    const later = buildIssue('later', 2, 3, { severity: 'warning' })
    const issues = ref<readonly VerificationIssue[]>([
      early,
      selected,
      later
    ])
    const navigation = useIssueNavigation({ issues })
    navigation.selectedSeverity.value = 'error'
    navigation.selectIssue(selected.issue_id)

    issues.value = [
      early,
      buildIssue('selected', 1, 2, { severity: 'warning' }),
      buildIssue('later', 2, 3, { severity: 'error' })
    ]
    await nextTick()

    expect(navigation.selectedIssueId.value).toBe(later.issue_id)
  })
})

describe('IssueDetails', () => {
  it('shows alternatives and marks the first actual alternative as recommended', () => {
    const issue = buildIssue('details', 0, 1)
    const wrapper = mount(IssueDetails, { props: { issue } })

    expect(wrapper.get('[data-recommended]').text()).toBe('备选一')
  })

  it('distinguishes no suggestion from deletion and removes duplicate alternatives', () => {
    const noSuggestion = mount(IssueDetails, {
      props: {
        issue: buildIssue('manual', 0, 1, {
          suggestion: null,
          alternatives: []
        })
      }
    })
    const deletion = mount(IssueDetails, {
      props: {
        issue: buildIssue('delete', 0, 1, {
          suggestion: '',
          alternatives: ['', '保留', '保留']
        })
      }
    })

    expect(noSuggestion.get('[data-suggestion]').text()).toContain('无自动建议')
    expect(deletion.get('[data-suggestion]').text()).toContain('删除')
    expect(deletion.findAll('[data-alternative]')).toHaveLength(1)
    expect(deletion.get('[data-recommended]').text()).toBe('保留')
  })

  it('allows a manual-only issue to select its only alternative', async () => {
    const wrapper = mount(IssueDetails, {
      props: {
        issue: buildIssue('manual-alternative', 0, 1, {
          suggestion: null,
          alternatives: ['人工替代']
        })
      }
    })

    await wrapper.get('[aria-label="选择修改建议"]').setValue('1')

    expect(wrapper.emitted('update:suggestion')?.[0]).toEqual(['人工替代'])
  })
})

describe('IssueList', () => {
  const issueStates: Readonly<Record<string, IssueState>> = Object.freeze({})
  let scrollIntoView: ReturnType<typeof vi.fn>

  beforeEach(() => {
    scrollIntoView = vi.fn()
    Object.defineProperty(HTMLElement.prototype, 'scrollIntoView', {
      configurable: true,
      value: scrollIntoView
    })
  })

  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it('activates the same stable id by click and keyboard', async () => {
    const issue = buildIssue('list-issue', 0, 1)
    const wrapper = mount(IssueList, {
      props: {
        issues: [issue],
        selectedIssueId: null,
        issueStates,
        selectedSuggestions: Object.freeze({})
      }
    })
    const control = wrapper.get(`[data-issue-id="${issue.issue_id}"]`)

    await control.trigger('click')
    await control.trigger('keydown', { key: 'Enter' })

    expect(wrapper.emitted('select-issue')).toEqual([
      [issue.issue_id],
      [issue.issue_id]
    ])
  })

  it('labels the list and exposes the current selection', () => {
    const issue = buildIssue('selected-list-issue', 0, 1)
    const wrapper = mount(IssueList, {
      props: {
        issues: [issue],
        selectedIssueId: issue.issue_id,
        issueStates,
        selectedSuggestions: Object.freeze({})
      }
    })

    expect(wrapper.get('[aria-label="问题列表"]').attributes('aria-label')).toBe(
      '问题列表'
    )
    expect(
      wrapper.get(`[data-issue-id="${issue.issue_id}"]`).attributes('aria-current')
    ).toBe('true')
  })

  it('scrolls a preselected list control when mounted', async () => {
    const issue = buildIssue('preselected-list-issue', 0, 1)
    const wrapper = mount(IssueList, {
      props: {
        issues: [issue],
        selectedIssueId: issue.issue_id,
        issueStates,
        selectedSuggestions: Object.freeze({})
      }
    })

    await nextTick()

    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('uses non-smooth list scrolling when reduced motion is preferred', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true }))
    )
    const issue = buildIssue('reduced-motion-list-issue', 0, 1)
    const wrapper = mount(IssueList, {
      props: {
        issues: [issue],
        selectedIssueId: issue.issue_id,
        issueStates,
        selectedSuggestions: Object.freeze({})
      }
    })

    await nextTick()

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'auto',
      block: 'center',
      inline: 'nearest'
    })
    wrapper.unmount()
  })

  it('scrolls the same selected list control after remount', async () => {
    const issue = buildIssue('remounted-list-issue', 0, 1)
    const props = {
      issues: [issue],
      selectedIssueId: issue.issue_id,
      issueStates,
      selectedSuggestions: Object.freeze({})
    }
    const first = mount(IssueList, { props })
    await nextTick()
    first.unmount()
    const second = mount(IssueList, { props })

    await nextTick()

    expect(scrollIntoView).toHaveBeenCalledTimes(2)
    second.unmount()
  })

  it('scrolls only the latest list selection after rapid changes', async () => {
    const firstIssue = buildIssue('rapid-list-a', 0, 1)
    const secondIssue = buildIssue('rapid-list-b', 1, 2)
    const wrapper = mount(IssueList, {
      props: {
        issues: [firstIssue, secondIssue],
        selectedIssueId: null,
        issueStates,
        selectedSuggestions: Object.freeze({})
      }
    })
    const firstScroll = vi.fn()
    const secondScroll = vi.fn()
    Object.defineProperty(
      wrapper.get(`[data-issue-id="${firstIssue.issue_id}"]`).element,
      'scrollIntoView',
      { configurable: true, value: firstScroll }
    )
    Object.defineProperty(
      wrapper.get(`[data-issue-id="${secondIssue.issue_id}"]`).element,
      'scrollIntoView',
      { configurable: true, value: secondScroll }
    )

    const firstUpdate = wrapper.setProps({
      selectedIssueId: firstIssue.issue_id
    })
    const secondUpdate = wrapper.setProps({
      selectedIssueId: secondIssue.issue_id
    })
    await Promise.all([firstUpdate, secondUpdate])
    await nextTick()

    expect(firstScroll).not.toHaveBeenCalled()
    expect(secondScroll).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('scrolls only inside the list instance whose selection changed', async () => {
    const issue = buildIssue('shared-list-issue', 0, 1)
    const props = {
      issues: [issue],
      selectedIssueId: null,
      issueStates,
      selectedSuggestions: Object.freeze({})
    }
    const first = mount(IssueList, { props, attachTo: document.body })
    const second = mount(IssueList, { props, attachTo: document.body })
    const firstScroll = vi.fn()
    const secondScroll = vi.fn()
    Object.defineProperty(
      first.get(`[data-issue-id="${issue.issue_id}"]`).element,
      'scrollIntoView',
      { configurable: true, value: firstScroll }
    )
    Object.defineProperty(
      second.get(`[data-issue-id="${issue.issue_id}"]`).element,
      'scrollIntoView',
      { configurable: true, value: secondScroll }
    )

    await first.setProps({ selectedIssueId: issue.issue_id })
    await nextTick()

    expect(firstScroll).toHaveBeenCalledTimes(1)
    expect(secondScroll).not.toHaveBeenCalled()
    first.unmount()
    second.unmount()
  })
})
