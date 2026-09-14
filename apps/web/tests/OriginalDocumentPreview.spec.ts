import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { fetchReviewLayout, type ReviewLayout } from '../src/api/originalPreview'
import OriginalDocumentPreview from '../src/components/workspace/OriginalDocumentPreview.vue'

vi.mock('../src/api/originalPreview', () => ({ fetchReviewLayout: vi.fn() }))

const issue = {
  issue_id: 'issue', start: 0, end: 2, original: '帐号', message: '错别字', severity: 'warning'
} as const
const props = {
  jobId: 'job', sourceVersion: 'sha256:source', text: '帐号测试',
  issues: [issue], selectedIssueId: 'issue', issueStates: {}
}

function layout(text = '帐号测试'): ReviewLayout {
  return {
    revision_applied: true, notice: null,
    pages: [{
      width: 600, height: 800, image: 'data:image/png;base64,AAAA', text,
      glyphs: Array.from(text, (_, start) => ({
        start, end: start + 1, x: 30 + start * 12, y: 60, width: 12, height: 14
      }))
    }]
  }
}

beforeEach(() => vi.mocked(fetchReviewLayout).mockReset())
afterEach(() => vi.unstubAllGlobals())

describe('unified original document review', () => {
  it('locates whitespace-only issues when rendering coalesces the space run', async () => {
    const rendered = layout('甲  乙')
    const page = rendered.pages[0]
    page.glyphs = [
      page.glyphs[0],
      { ...page.glyphs[1], start: 1, end: 3 },
      page.glyphs[3]
    ]
    vi.mocked(fetchReviewLayout).mockResolvedValue(rendered)
    const wrapper = mount(OriginalDocumentPreview, {
      props: {
        ...props, text: '甲  乙',
        issues: [{ ...issue, start: 1, end: 3, original: '  ', message: '存在连续多个空格' }]
      }
    })
    await flushPromises()
    expect(wrapper.find('[data-location-warning]').exists()).toBe(false)
    const mark = wrapper.get<HTMLButtonElement>('.layout-issue.selected')
    expect(parseFloat(mark.element.style.left)).toBeCloseTo(7)
    expect(parseFloat(mark.element.style.width)).toBeCloseTo(2)
    await mark.trigger('click')
    expect(wrapper.emitted('select-issue')).toEqual([['issue']])
    wrapper.unmount()
  })

  it('defers offscreen marks while keeping selected-page navigation available', async () => {
    const visibility: Array<(visible: boolean) => void> = []
    vi.stubGlobal('IntersectionObserver', class {
      constructor(callback: (entries: Array<{ isIntersecting: boolean }>) => void) {
        visibility.push((visible) => callback([{ isIntersecting: visible }]))
      }
      observe() {}
      disconnect() {}
    })
    const rendered = layout()
    rendered.pages.push({
      ...layout('正文').pages[0],
      glyphs: layout('正文').pages[0].glyphs.map((glyph) => ({
        ...glyph, start: glyph.start + 4, end: glyph.end + 4
      }))
    })
    const second = { ...issue, issue_id: 'second', start: 4, end: 6, original: '正文' }
    vi.mocked(fetchReviewLayout).mockResolvedValue(rendered)
    const wrapper = mount(OriginalDocumentPreview, {
      props: { ...props, issues: [issue, second] }
    })
    await flushPromises()
    expect(wrapper.findAll('.layout-page')).toHaveLength(2)
    expect(wrapper.find('[data-issue-id="second"]').exists()).toBe(false)
    expect(wrapper.get('.layout-page:nth-child(2) img').attributes('loading')).toBe('lazy')
    await wrapper.setProps({ selectedIssueId: 'second' })
    expect(wrapper.get('[data-issue-id="second"]').attributes('aria-current')).toBe('true')
    expect(wrapper.find('[data-location-warning]').exists()).toBe(false)
    await wrapper.setProps({ selectedIssueId: null })
    expect(wrapper.find('[data-issue-id="second"]').exists()).toBe(false)
    visibility[1](true)
    await flushPromises()
    expect(wrapper.find('[data-issue-id="second"]').exists()).toBe(true)
    visibility[1](false)
    await wrapper.setProps({ searchMatches: [{ start: 4, end: 6 }], activeSearchMatchIndex: 0 })
    expect(wrapper.get('[data-search-match="0"]').classes()).toContain('active')
    wrapper.unmount()
  })

  it('supports reducing and restoring the page scale without changing issue coordinates', async () => {
    vi.mocked(fetchReviewLayout).mockResolvedValue(layout())
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    const select = wrapper.get('select[aria-label="文档缩放"]')
    const markStyle = wrapper.get('[data-issue-role="source"]').attributes('style')
    for (const scale of [25, 50, 75, 100, 125, 150, 200]) {
      expect(select.findAll('option').some((option) =>
        option.text() === `${scale}%`
      )).toBe(true)
      await select.setValue(String(scale))
      expect(wrapper.get('.layout-pages').attributes('style')).toContain(`width: ${scale}%`)
      expect(wrapper.get('[data-issue-role="source"]').attributes('style')).toBe(markStyle)
    }
    await select.setValue('fit')
    expect(wrapper.get('.layout-pages').attributes('style')).toContain('width: 100%')
    expect(wrapper.get('.layout-page img').attributes('src')).toBe('data:image/png;base64,AAAA')
    wrapper.unmount()
  })

  it('shows page images and clickable issue marks together without PDF viewer modes', async () => {
    vi.mocked(fetchReviewLayout).mockResolvedValue(layout())
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    expect(wrapper.get('.layout-page img').attributes('src')).toBe('data:image/png;base64,AAAA')
    expect(wrapper.find('iframe').exists()).toBe(false)
    const mark = wrapper.get('[data-issue-role="source"]')
    expect(mark.attributes('data-issue-id')).toBe('issue')
    expect(mark.attributes('style')).toContain('left: 5%')
    await mark.trigger('click')
    expect(wrapper.emitted('select-issue')).toEqual([['issue']])
    wrapper.unmount()
  })

  it('refreshes the page after a revision and undo, without remounting the workspace', async () => {
    vi.mocked(fetchReviewLayout)
      .mockResolvedValueOnce(layout()).mockResolvedValueOnce(layout('账号测试'))
      .mockResolvedValueOnce(layout())
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    await wrapper.setProps({ text: '账号测试', issues: [{ ...issue, original: '账号' }] })
    await flushPromises()
    expect(wrapper.get('.layout-page img').attributes('alt')).toContain('账号测试')
    await wrapper.setProps({ text: '帐号测试', issues: [issue] })
    await flushPromises()
    expect(wrapper.get('.layout-page img').attributes('alt')).toContain('帐号测试')
    wrapper.unmount()
  })

  it('does not display stale marks while a newer revision is being rendered', async () => {
    let finish!: (value: ReviewLayout) => void
    vi.mocked(fetchReviewLayout)
      .mockResolvedValueOnce(layout())
      .mockImplementationOnce(() => new Promise((resolve) => { finish = resolve }))
      .mockResolvedValueOnce(layout('最新测试'))
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    await wrapper.setProps({ text: '中间测试' })
    expect(wrapper.find('[data-issue-role="source"]').exists()).toBe(false)
    await wrapper.setProps({ text: '最新测试' })
    finish(layout('中间测试'))
    await flushPromises()
    expect(wrapper.get('.layout-page img').attributes('alt')).toContain('最新测试')
    wrapper.unmount()
  })

  it('reports unavailable coordinates rather than pointing at unrelated text', async () => {
    const unmapped = layout()
    unmapped.pages[0].glyphs = []
    vi.mocked(fetchReviewLayout).mockResolvedValue(unmapped)
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    expect(wrapper.get('[data-location-warning]').text()).toContain('无法精确定位')
    expect(wrapper.find('[data-issue-role="source"]').exists()).toBe(false)
    wrapper.unmount()
  })

  it('keeps renderer errors explicit and supports retry', async () => {
    vi.mocked(fetchReviewLayout)
      .mockRejectedValueOnce(new Error('原文件已过期')).mockResolvedValueOnce(layout())
    const wrapper = mount(OriginalDocumentPreview, { props })
    await flushPromises()
    expect(wrapper.get('[role="alert"]').text()).toContain('原文件已过期')
    await wrapper.get('[data-retry-preview]').trigger('click')
    await flushPromises()
    expect(wrapper.find('.layout-page').exists()).toBe(true)
    wrapper.unmount()
  })

  it('places search highlights in the same document view', async () => {
    vi.mocked(fetchReviewLayout).mockResolvedValue(layout())
    const wrapper = mount(OriginalDocumentPreview, { props: {
      ...props, searchMatches: [{ start: 2, end: 4 }], activeSearchMatchIndex: 0
    } })
    await flushPromises()
    expect(wrapper.get('[data-search-match="0"]').attributes('style')).toContain('left: 9%')
    wrapper.unmount()
  })
})
