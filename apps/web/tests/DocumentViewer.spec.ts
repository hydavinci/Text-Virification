import { mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import DocumentViewer from '../src/components/workspace/DocumentViewer.vue'
import type {
  TextBlock,
  VerificationIssue,
  VerificationResult
} from '../src/types/verification'

const documentId = '11111111-1111-1111-1111-111111111111'
const runId = '22222222-2222-2222-2222-222222222222'

function buildIssue(
  overrides: Partial<VerificationIssue> = {}
): VerificationIssue {
  return {
    issue_id: '33333333-3333-3333-3333-333333333333',
    document_id: documentId,
    verification_run_id: runId,
    block_id: 'p-0',
    page: null,
    start: 1,
    end: 3,
    block_start: 1,
    block_end: 3,
    type: 'typo',
    severity: 'warning',
    original: '乙丙',
    suggestion: 'BC',
    alternatives: ['备选'],
    layer: 'character',
    message: '疑似错别字',
    description: '疑似错别字',
    rule_id: 'cn_typo',
    rule_version: '1',
    source: 'test',
    source_version: '1',
    confidence: 0.8,
    auto_fixable: true,
    context: '甲乙丙丁',
    position: 99,
    end_position: 100,
    review: null,
    review_reason: null,
    ...overrides
  }
}

function buildBlock(text: string): TextBlock {
  const length = Array.from(text).length
  return {
    block_id: 'p-0',
    kind: 'paragraph',
    text,
    global_start: 0,
    global_end: length,
    block_start: 0,
    block_end: length,
    page: null,
    paragraph_index: 0,
    table_index: null,
    row_index: null,
    cell_index: null,
    bbox: null,
    parent_id: null,
    style: {},
    source_locator: { paragraph_index: 0 }
  }
}

function buildResult(
  text: string,
  issues: VerificationIssue[]
): VerificationResult {
  const length = Array.from(text).length
  return {
    success: true,
    filename: 'sample.txt',
    source_name: 'sample.txt',
    file_type: 'txt',
    text,
    blocks: [buildBlock(text)],
    parser_name: 'compatibility-flat-text',
    parser_version: '1',
    stats: {
      char_count: length,
      char_count_no_space: length,
      line_count: text.split('\n').length,
      paragraph_count: 1,
      language: 'zh',
      primary_count: length,
      primary_label: '总字数'
    },
    issues,
    summary: {
      total: issues.length,
      by_type: { typo: issues.length },
      by_severity: { warning: issues.length },
      by_rule: { cn_typo: issues.length },
      by_layer: { character: issues.length }
    },
    file_id: null,
    file_ext: null,
    document_id: documentId,
    verification_run_id: runId,
    source_version:
      'sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
    execution_mode: 'synchronous',
    analysis_mode: 'local_only',
    dictionary_versions: {},
    degradation: { is_degraded: false, reasons: [] },
    scenario: 'general'
  }
}

describe('DocumentViewer', () => {
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

  it('selects an issue by stable id when its source control is activated', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    await wrapper.get(`[data-issue-id="${issue.issue_id}"]`).trigger('click')

    expect(wrapper.emitted('select-issue')?.[0]).toEqual([issue.issue_id])
  })

  it('renders source characters as text without interpreting markup', () => {
    const text = '甲 <img src=x onerror=alert(1)>\n乙'
    const result = buildResult(text, [])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: [], selectedIssueId: null, mode: 'continuous' }
    })

    expect(wrapper.get('[data-source-text]').text()).toBe(text)
    expect(wrapper.find('img').exists()).toBe(false)
  })

  it('preserves exact text and line numbers in sentence mode', () => {
    const text = '第一行  \n\n第三行\n'
    const result = buildResult(text, [])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: [], selectedIssueId: null, mode: 'sentence' }
    })

    expect(
      wrapper
        .findAll('[data-source-line]')
        .map((line) => line.element.textContent ?? '')
        .join('')
    ).toBe(text)
    expect(
      wrapper.findAll('[data-line-number]').map((line) => line.text())
    ).toEqual(['1', '2', '3', '4'])
  })

  it('uses code-point offsets after astral characters', () => {
    const text = '甲😀乙丙'
    const issue = buildIssue({
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '乙'
    })
    const result = buildResult(text, [issue])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    expect(wrapper.get(`[data-issue-id="${issue.issue_id}"]`).attributes('aria-label'))
      .toContain('乙')
    expect(wrapper.get('[data-source-text]').text()).toBe(text)
  })

  it('keeps every crossing overlap navigable while rendering source text once', () => {
    const text = '甲乙丙丁戊'
    const first = buildIssue({
      issue_id: '33333333-3333-3333-3333-333333333333',
      start: 0,
      end: 3,
      block_start: 0,
      block_end: 3,
      original: '甲乙丙'
    })
    const second = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 5,
      block_start: 2,
      block_end: 5,
      original: '丙丁戊'
    })
    const result = buildResult(text, [first, second])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    expect(wrapper.findAll(`[data-issue-id="${first.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.findAll(`[data-issue-id="${second.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.find('.source-segment.overlapping').exists()).toBe(true)
    expect(wrapper.get('[data-source-text]').text()).toBe(text)
  })

  it('keeps nested overlaps navigable while rendering source text once', () => {
    const text = '甲乙丙丁戊'
    const outer = buildIssue({
      issue_id: '33333333-3333-3333-3333-333333333333',
      start: 0,
      end: 5,
      block_start: 0,
      block_end: 5,
      original: text
    })
    const inner = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 1,
      end: 4,
      block_start: 1,
      block_end: 4,
      original: '乙丙丁'
    })
    const result = buildResult(text, [outer, inner])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    expect(wrapper.findAll(`[data-issue-id="${outer.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.findAll(`[data-issue-id="${inner.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.get('[data-source-text]').text()).toBe(text)
  })

  it('keeps identical ranges navigable while rendering source text once', () => {
    const text = '甲乙丙丁'
    const first = buildIssue({
      issue_id: '33333333-3333-3333-3333-333333333333'
    })
    const second = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444'
    })
    const result = buildResult(text, [first, second])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    expect(wrapper.findAll(`[data-issue-id="${first.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.findAll(`[data-issue-id="${second.issue_id}"]`)).toHaveLength(1)
    expect(wrapper.get('[data-source-text]').text()).toBe(text)
  })

  it('renders an empty source exactly once without source markers', () => {
    const result = buildResult('', [])
    const wrapper = mount(DocumentViewer, {
      props: {
        result,
        issues: result.issues,
        selectedIssueId: null,
        mode: 'sentence'
      }
    })

    expect(wrapper.get('[data-source-text]').text()).toBe('')
    expect(wrapper.findAll('[data-issue-role="source"]')).toHaveLength(0)
    expect(wrapper.findAll('[data-line-number]')).toHaveLength(1)
  })

  it('supports keyboard activation and exposes the current source selection', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: issue.issue_id }
    })
    const control = wrapper.get(`[data-issue-id="${issue.issue_id}"]`)

    await control.trigger('keydown', { key: 'Enter' })

    expect(control.attributes('aria-current')).toBe('true')
    expect(wrapper.emitted('select-issue')?.[0]).toEqual([issue.issue_id])
  })

  it('preserves accepted and rejected source marker states by issue id', () => {
    const accepted = buildIssue()
    const rejected = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 3,
      end: 4,
      block_start: 3,
      block_end: 4,
      original: '丁'
    })
    const result = buildResult('甲乙丙丁', [accepted, rejected])
    const wrapper = mount(DocumentViewer, {
      props: {
        result,
        issues: result.issues,
        selectedIssueId: null,
        issueStates: {
          [accepted.issue_id]: 'accepted',
          [rejected.issue_id]: 'rejected'
        }
      }
    })

    expect(
      wrapper.get(`[data-issue-id="${accepted.issue_id}"]`).classes()
    ).toContain('accepted')
    expect(
      wrapper.get(`[data-issue-id="${rejected.issue_id}"]`).classes()
    ).toContain('rejected')
  })

  it('scrolls the newly selected source control after render when supported', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const wrapper = mount(DocumentViewer, {
      attachTo: document.body,
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    await wrapper.setProps({ selectedIssueId: issue.issue_id })
    await wrapper.vm.$nextTick()

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'center',
      inline: 'nearest'
    })
    wrapper.unmount()
  })

  it('uses non-smooth source scrolling when reduced motion is preferred', async () => {
    vi.stubGlobal(
      'matchMedia',
      vi.fn(() => ({ matches: true }))
    )
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const wrapper = mount(DocumentViewer, {
      props: { result, issues: result.issues, selectedIssueId: null }
    })

    await wrapper.setProps({ selectedIssueId: issue.issue_id })
    await wrapper.vm.$nextTick()

    expect(scrollIntoView).toHaveBeenCalledWith({
      behavior: 'auto',
      block: 'center',
      inline: 'nearest'
    })
  })

  it('scrolls a preselected source control when mounted', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const wrapper = mount(DocumentViewer, {
      props: {
        result,
        issues: result.issues,
        selectedIssueId: issue.issue_id
      }
    })

    await wrapper.vm.$nextTick()

    expect(scrollIntoView).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('scrolls the same selected source control after remount', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const props = {
      result,
      issues: result.issues,
      selectedIssueId: issue.issue_id
    }
    const first = mount(DocumentViewer, { props })
    await first.vm.$nextTick()
    first.unmount()
    const second = mount(DocumentViewer, { props })

    await second.vm.$nextTick()

    expect(scrollIntoView).toHaveBeenCalledTimes(2)
    second.unmount()
  })

  it('scrolls only the latest source selection after rapid changes', async () => {
    const firstIssue = buildIssue({
      issue_id: '33333333-3333-3333-3333-333333333333',
      start: 0,
      end: 1,
      block_start: 0,
      block_end: 1,
      original: '甲'
    })
    const secondIssue = buildIssue({
      issue_id: '44444444-4444-4444-4444-444444444444',
      start: 2,
      end: 3,
      block_start: 2,
      block_end: 3,
      original: '丙'
    })
    const result = buildResult('甲乙丙丁', [firstIssue, secondIssue])
    const wrapper = mount(DocumentViewer, {
      props: {
        result,
        issues: result.issues,
        selectedIssueId: null
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
    await wrapper.vm.$nextTick()

    expect(firstScroll).not.toHaveBeenCalled()
    expect(secondScroll).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('scrolls only inside the viewer instance whose selection changed', async () => {
    const issue = buildIssue()
    const result = buildResult('甲乙丙丁', [issue])
    const props = {
      result,
      issues: result.issues,
      selectedIssueId: null
    }
    const first = mount(DocumentViewer, { props, attachTo: document.body })
    const second = mount(DocumentViewer, { props, attachTo: document.body })
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
    await first.vm.$nextTick()

    expect(firstScroll).toHaveBeenCalledTimes(1)
    expect(secondScroll).not.toHaveBeenCalled()
    first.unmount()
    second.unmount()
  })
})
