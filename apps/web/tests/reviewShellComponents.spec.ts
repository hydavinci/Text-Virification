import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ContextInspector from '../src/components/review/ContextInspector.vue'
import DocumentHeader from '../src/components/review/DocumentHeader.vue'
import WorkspaceSidePanel from '../src/components/review/WorkspaceSidePanel.vue'
import OperationHistory from '../src/components/review/OperationHistory.vue'
import ToolRail from '../src/components/review/ToolRail.vue'

describe('ToolRail', () => {
  it('keeps rail mode at 64px and exposes a structural active marker', async () => {
    const wrapper = mount(ToolRail, {
      props: {
        mode: 'rail',
        activeTool: 'issues',
        sidePanelOpen: true,
        exportOpen: false
      }
    })

    expect(wrapper.get('nav').attributes('aria-label')).toBe('审阅工具')
    expect(wrapper.get('nav').attributes('style')).toContain('width: 64px')
    expect(wrapper.text()).toContain('问题')
    expect(wrapper.text()).toContain('查找')
    expect(wrapper.text()).toContain('批量')
    expect(wrapper.text()).toContain('历史')
    expect(wrapper.text()).toContain('导出')
    expect(wrapper.find('[data-tool="document"]').exists()).toBe(false)
    expect(wrapper.get('[data-tool="history"]').attributes('aria-pressed')).toBe('false')
    expect(wrapper.get('[data-tool="issues"]').attributes('aria-pressed')).toBe('true')
    expect(wrapper.get('[data-tool="issues"] .tool-rail__active-indicator').text()).toBe('✓')
    expect(wrapper.find('[data-tool="search"] .tool-rail__active-indicator').exists()).toBe(false)

    await wrapper.get('[data-tool="issues"]').trigger('click')
    expect(wrapper.emitted('activate')).toEqual([['issues']])
  })

  it('adds document in bottom mode and supports roving keyboard focus', async () => {
    const wrapper = mount(ToolRail, {
      attachTo: document.body,
      props: {
        mode: 'bottom',
        activeTool: 'document',
        sidePanelOpen: false,
        exportOpen: false
      }
    })
    const documentButton = wrapper.get('[data-tool="document"]')

    await documentButton.trigger('keydown', { key: 'ArrowRight' })

    expect(document.activeElement).toBe(wrapper.get('[data-tool="issues"]').element)
    wrapper.unmount()
  })

  it('reports export state and exposes typed tool focus methods', () => {
    const wrapper = mount(ToolRail, {
      attachTo: document.body,
      props: {
        mode: 'rail',
        activeTool: 'issues',
        sidePanelOpen: false,
        exportOpen: true
      }
    })

    expect(wrapper.get('[data-tool="export"]').attributes('aria-expanded')).toBe('true')
    expect(wrapper.get('[data-tool="export"] .tool-rail__active-indicator').text()).toBe('✓')
    const rail = wrapper.vm as {
      focusExportButton(): void
      focusTool(tool: 'issues' | 'batch' | 'history'): void
    }
    rail.focusExportButton()
    expect(document.activeElement).toBe(wrapper.get('[data-tool="export"]').element)
    rail.focusTool('history')
    expect(document.activeElement).toBe(wrapper.get('[data-tool="history"]').element)
    wrapper.unmount()
  })


  it('adds history to bottom navigation and keeps export keyboard order after it', async () => {
    const wrapper = mount(ToolRail, {
      attachTo: document.body,
      props: {
        mode: 'bottom',
        activeTool: 'history',
        sidePanelOpen: false,
        exportOpen: false
      }
    })

    expect(wrapper.get('[data-tool="history"]').attributes('aria-current')).toBeUndefined()
    expect(wrapper.get('[data-tool="history"]').attributes('aria-pressed')).toBe('true')

    await wrapper.get('[data-tool="history"]').trigger('keydown', { key: 'ArrowRight' })
    expect(document.activeElement).toBe(wrapper.get('[data-tool="export"]').element)
    wrapper.unmount()
  })
})

describe('review shell containers', () => {
  it('renders file metadata and retries a failed summary', async () => {
    const wrapper = mount(DocumentHeader, {
      props: {
        sourceName: 'contract.docx',
        fileType: 'docx',
        loadedParagraphCount: 42,
        totalIssues: 7,
        loading: false,
        error: '总览加载失败'
      }
    })

    expect(wrapper.text()).toContain('contract.docx')
    expect(wrapper.text()).toContain('DOCX')
    expect(wrapper.text()).toContain('42 个已加载段落')
    expect(wrapper.text()).toContain('7 个问题')
    expect(wrapper.get('[role="alert"]').text()).toContain('总览加载失败')

    await wrapper.get('button').trigger('click')

    expect(wrapper.emitted('retry')).toHaveLength(1)
  })

  it('labels and closes the optional side panel', async () => {
    const wrapper = mount(WorkspaceSidePanel, {
      props: { open: true, title: '问题' },
      slots: { default: '<p>问题内容</p>' }
    })

    expect(wrapper.get('aside').attributes('aria-label')).toBe('问题')
    expect(wrapper.text()).toContain('问题内容')

    await wrapper.get('button[aria-label="关闭问题面板"]').trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
  })


  it('renders a local latest batch even before history is loaded', () => {
    const wrapper = mount(OperationHistory, {
      props: {
        historyPage: null,
        latestBatch: {
          batch_id: 'batch-1',
          job_id: 'job-1',
          version_id: 'version-2',
          operation_type: 'decision',
          affected_count: 2,
          undoes_batch_id: null,
          created_at: '2026-08-23T12:00:00Z'
        },
        canUndoLatestBatch: true,
        undoConflict: null,
        busy: false
      }
    })

    expect(wrapper.get('[data-testid="operation-history"]').text()).toContain('处理决定')
    expect(wrapper.get('[data-testid="operation-history"]').text()).toContain('2 项')
  })

  it('implements arrow, Home, and End tab navigation', async () => {
    const wrapper = mount(ContextInspector, {
      attachTo: document.body,
      props: { activeTab: 'details' },
      slots: { details: '详情内容', search: '查找内容' }
    })
    const detailsTab = wrapper.get('[role="tab"][data-tab="details"]')

    expect(detailsTab.get('.context-inspector__tab-indicator').text()).toBe('✓')
    expect(wrapper.find('[data-tab="search"] .context-inspector__tab-indicator').exists()).toBe(false)

    await detailsTab.trigger('keydown', { key: 'ArrowRight' })
    expect(wrapper.emitted('update:activeTab')).toEqual([['search']])

    await wrapper.setProps({ activeTab: 'search' })
    expect(document.activeElement).toBe(wrapper.get('[data-tab="search"]').element)

    await wrapper.get('[data-tab="search"]').trigger('keydown', { key: 'Home' })
    expect(wrapper.emitted('update:activeTab')?.at(-1)).toEqual(['details'])
    wrapper.unmount()
  })
})
