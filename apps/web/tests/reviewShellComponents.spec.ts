import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

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
