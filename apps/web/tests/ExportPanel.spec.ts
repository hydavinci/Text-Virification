import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ExportPanel from '../src/components/workspace/ExportPanel.vue'

describe('ExportPanel', () => {
  it('emits labelled report, revision export, recheck, and tracked-change actions', async () => {
    const wrapper = mount(ExportPanel, {
      props: {
        trackChanges: true,
        reportDisabled: false,
        modifiedDisabled: false,
        recheckDisabled: false,
        busy: false
      }
    })

    await wrapper.get('[data-action="recheck"]').trigger('click')
    await wrapper.get('[data-action="export-report"]').trigger('click')
    await wrapper.get('[data-action="export-modified"]').trigger('click')
    await wrapper.get<HTMLInputElement>('[data-track-changes]').setValue(false)

    expect(wrapper.emitted('recheck')).toHaveLength(1)
    expect(wrapper.emitted('export-report')).toHaveLength(1)
    expect(wrapper.emitted('export-modified')).toHaveLength(1)
    expect(wrapper.emitted('update:trackChanges')?.[0]).toEqual([false])
    expect(
      wrapper.get<HTMLInputElement>('[data-track-changes]').attributes('aria-label')
    ).toBe('导出时保留修订标记')
  })

  it('blocks revision export while conflicts or re-verification make it unsafe', () => {
    const wrapper = mount(ExportPanel, {
      props: {
        trackChanges: true,
        reportDisabled: true,
        modifiedDisabled: true,
        recheckDisabled: false,
        busy: false,
        blockedReason: '当前文本需要重新检查'
      }
    })

    expect(
      wrapper.get<HTMLButtonElement>('[data-action="export-report"]').element.disabled
    ).toBe(true)
    expect(
      wrapper.get<HTMLButtonElement>('[data-action="export-modified"]').element.disabled
    ).toBe(true)
    expect(wrapper.get('[role="status"]').text()).toContain('重新检查')
  })
})
