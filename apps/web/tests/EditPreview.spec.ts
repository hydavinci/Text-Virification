import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import EditPreview from '../src/components/workspace/EditPreview.vue'

function mountEditor() {
  const host = document.createElement('div')
  document.body.append(host)
  const wrapper = mount(EditPreview, {
    attachTo: host,
    props: {
      text: '当前修订'
    },
    slots: {
      default: '<div data-source-content>源文档视图</div>'
    }
  })
  return { host, wrapper }
}

describe('EditPreview', () => {
  it('opens from current revision text and cancel restores without saving', async () => {
    const { host, wrapper } = mountEditor()

    await wrapper.get('[data-action="start-edit"]').trigger('click')
    const editor = wrapper.get<HTMLTextAreaElement>('[data-edit-input]')
    expect(editor.element.value).toBe('当前修订')
    expect(document.activeElement).toBe(editor.element)

    await editor.setValue('未保存文本')
    await wrapper.get('[data-action="cancel-edit"]').trigger('click')

    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.find('[data-source-content]').exists()).toBe(true)
    expect(document.activeElement).toBe(
      wrapper.get('[data-action="start-edit"]').element
    )
    wrapper.unmount()
    host.remove()
  })

  it('treats unchanged save as a no-op with deterministic live feedback', async () => {
    const { host, wrapper } = mountEditor()

    await wrapper.get('[data-action="start-edit"]').trigger('click')
    await wrapper.get('[data-action="save-edit"]').trigger('click')

    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.get('[data-edit-status]').text()).toBe('内容未发生变化')
    expect(wrapper.find('[data-edit-input]').exists()).toBe(false)
    wrapper.unmount()
    host.remove()
  })

  it('rejects empty or whitespace-only free edits without creating a revision', async () => {
    const { host, wrapper } = mountEditor()

    await wrapper.get('[data-action="start-edit"]').trigger('click')
    await wrapper.get('[data-edit-input]').setValue(' \n\t ')
    await wrapper.get('[data-action="save-edit"]').trigger('click')

    expect(wrapper.emitted('save')).toBeUndefined()
    expect(wrapper.get('[data-edit-status]').text()).toBe('内容不能为空')
    expect(wrapper.find('[data-edit-input]').exists()).toBe(true)
    wrapper.unmount()
    host.remove()
  })

  it('emits one changed nonempty save and returns to the document', async () => {
    const { host, wrapper } = mountEditor()

    await wrapper.get('[data-action="start-edit"]').trigger('click')
    await wrapper.get('[data-edit-input]').setValue('手工修改后的全文')
    await wrapper.get('[data-action="save-edit"]').trigger('click')

    expect(wrapper.emitted('save')).toEqual([['手工修改后的全文']])
    expect(wrapper.get('[data-edit-status]').text()).toBe(
      '编辑已保存，需要重新检查'
    )

    expect(wrapper.find('[data-source-content]').exists()).toBe(true)
    expect(wrapper.get('[data-action="start-edit"]').text()).toBe('编辑正文')
    wrapper.unmount()
    host.remove()
  })

  it('preserves the marker preference through editing and locks it when disabled', async () => {
    const { host, wrapper } = mountEditor()
    const toggle = () => wrapper.get<HTMLInputElement>(
      'input[aria-label="显示问题标记"]'
    )

    expect(toggle().element.checked).toBe(true)
    await toggle().setValue(false)
    expect(toggle().element.checked).toBe(false)
    await wrapper.get('[data-action="start-edit"]').trigger('click')
    expect(wrapper.find('input[aria-label="显示问题标记"]').exists()).toBe(false)
    await wrapper.get('[data-action="cancel-edit"]').trigger('click')
    expect(toggle().element.checked).toBe(false)

    await wrapper.setProps({ disabled: true })
    expect(toggle().element.disabled).toBe(true)
    await wrapper.setProps({ disabled: false })
    await toggle().setValue(true)
    expect(toggle().element.checked).toBe(true)
    wrapper.unmount()
    host.remove()
  })

  it('blocks a stale draft when the current revision changes during editing', async () => {
    const { host, wrapper } = mountEditor()

    await wrapper.get('[data-action="start-edit"]').trigger('click')
    await wrapper.get('[data-edit-input]').setValue('基于旧修订的草稿')
    await wrapper.setProps({ text: '并发产生的新修订' })

    expect(wrapper.get('[data-edit-status]').text()).toBe(
      '文档已更新，请取消后重新编辑'
    )
    expect(
      wrapper.get<HTMLButtonElement>('[data-action="save-edit"]').element
        .disabled
    ).toBe(true)
    expect(wrapper.emitted('save')).toBeUndefined()

    await wrapper.get('[data-action="cancel-edit"]').trigger('click')
    expect(document.activeElement).toBe(
      wrapper.get('[data-action="start-edit"]').element
    )
    await wrapper.get('[data-action="start-edit"]').trigger('click')
    expect(
      wrapper.get<HTMLTextAreaElement>('[data-edit-input]').element.value
    ).toBe('并发产生的新修订')
    wrapper.unmount()
    host.remove()
  })
})
