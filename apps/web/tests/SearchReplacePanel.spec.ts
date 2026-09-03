import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SearchReplacePanel from '../src/components/workspace/SearchReplacePanel.vue'

describe('SearchReplacePanel', () => {
  it('exposes labelled literal search and live cyclic navigation status', async () => {
    const wrapper = mount(SearchReplacePanel, {
      props: { text: 'a.b a.b' }
    })

    await wrapper.get('[data-search-input]').setValue('a.b')

    const status = wrapper.get('[data-search-status]')
    expect(status.attributes('role')).toBe('status')
    expect(status.attributes('aria-live')).toBe('polite')
    expect(status.text()).toBe('第 1 项，共 2 项')

    await wrapper.get('[data-action="search-previous"]').trigger('click')
    expect(status.text()).toBe('第 2 项，共 2 项')
    await wrapper.get('[data-action="search-next"]').trigger('click')
    expect(status.text()).toBe('第 1 项，共 2 项')
  })

  it('emits one current deletion or replace-all action from current text', async () => {
    const wrapper = mount(SearchReplacePanel, {
      props: { text: 'Aa😀aa' }
    })

    await wrapper.get('[data-search-input]').setValue('aa')
    await wrapper.get('[data-replacement-input]').setValue('')
    await wrapper.get('[data-action="replace-current"]').trigger('click')
    expect(wrapper.emitted('replace-text')).toEqual([
      ['😀aa', 'current', 1]
    ])

    await wrapper.setProps({ text: 'Aa😀aa' })
    await wrapper.get('[data-replacement-input]').setValue('X')
    await wrapper.get('[data-action="replace-all"]').trigger('click')
    expect(wrapper.emitted('replace-text')).toEqual([
      ['😀aa', 'current', 1],
      ['X😀X', 'all', 2]
    ])
  })

  it('has stable action selectors, explicit labels, and a close event', async () => {
    const wrapper = mount(SearchReplacePanel, {
      props: { text: 'text' }
    })

    expect(wrapper.get('[data-search-input]').attributes('aria-label')).toBe(
      '查找内容'
    )
    expect(
      wrapper.get('[data-replacement-input]').attributes('aria-label')
    ).toBe('替换内容')
    expect(
      wrapper.get('[data-case-sensitive]').attributes('aria-label')
    ).toBe('区分大小写')

    await wrapper.get('[data-action="close-search-replace"]').trigger('click')
    expect(wrapper.emitted('close')).toHaveLength(1)
  })
})
