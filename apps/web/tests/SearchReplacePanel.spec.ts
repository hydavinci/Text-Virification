import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import SearchReplacePanel from '../src/components/workspace/SearchReplacePanel.vue'

describe('SearchReplacePanel', () => {
  it('retains legacy Enter and Shift+Enter search navigation without consuming IME input', async () => {
    const wrapper = mount(SearchReplacePanel, { props: { text: '热点 热点 热点' } })
    const input = wrapper.get('[data-search-input]')
    await input.setValue('热点')
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.get('[data-search-status]').text()).toBe('第 2 项，共 3 项')
    await input.trigger('keydown', { key: 'Enter', shiftKey: true })
    expect(wrapper.get('[data-search-status]').text()).toBe('第 1 项，共 3 项')
    await input.trigger('keydown', { key: 'Enter', isComposing: true })
    expect(wrapper.get('[data-search-status]').text()).toBe('第 1 项，共 3 项')
    await wrapper.setProps({ disabled: true })
    await input.trigger('keydown', { key: 'Enter' })
    expect(wrapper.get('[data-search-status]').text()).toBe('第 1 项，共 3 项')
    wrapper.unmount()
  })

  it('publishes code-point matches and the active index for document navigation', async () => {
    const wrapper = mount(SearchReplacePanel, {
      props: { text: '😀热点 热点' }
    })
    await wrapper.get('[data-search-input]').setValue('热点')
    expect(wrapper.emitted('search-change')?.at(-1)).toEqual([{
      text: '😀热点 热点',
      matches: [{ start: 1, end: 3 }, { start: 4, end: 6 }],
      activeMatchIndex: 0
    }])
    await wrapper.get('[data-action="search-next"]').trigger('click')
    expect(wrapper.emitted('search-change')?.at(-1)?.[0]).toMatchObject({
      activeMatchIndex: 1
    })
    await wrapper.setProps({ text: '已修改' })
    expect(wrapper.emitted('search-change')?.at(-1)?.[0]).toMatchObject({
      text: '已修改', matches: []
    })
    wrapper.unmount()
  })

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

  it('keeps labelled search controls available after clearing the query', async () => {
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

    await wrapper.get('[data-search-input]').setValue('text')
    await wrapper.get('[data-search-input]').setValue('')
    expect(wrapper.get('[data-search-input]').isVisible()).toBe(true)
    expect(wrapper.get('[data-search-status]').text()).toBe('未找到匹配项')
    expect(wrapper.find('[data-action="close-search-replace"]').exists()).toBe(false)
  })
})
