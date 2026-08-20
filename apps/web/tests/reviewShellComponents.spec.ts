import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ContextInspector from '../src/components/review/ContextInspector.vue'
import WorkspaceSidePanel from '../src/components/review/WorkspaceSidePanel.vue'
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
    expect(wrapper.text()).toContain('导出')
    expect(wrapper.find('[data-tool="document"]').exists()).toBe(false)
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

  it('reports export state and exposes trigger focus', () => {
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
    ;(wrapper.vm as { focusExportButton(): void }).focusExportButton()
    expect(document.activeElement).toBe(wrapper.get('[data-tool="export"]').element)
    wrapper.unmount()
  })
})

describe('review shell containers', () => {
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
