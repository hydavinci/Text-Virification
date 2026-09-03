import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SourceInputPanel from '../src/components/workspace/SourceInputPanel.vue'

describe('SourceInputPanel', () => {
  it.each([
    { modifier: 'ctrlKey', label: 'Ctrl+Enter' },
    { modifier: 'metaKey', label: 'Meta+Enter' }
  ])('submits trimmed text with $label', async ({ modifier }) => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-mode="text"]').trigger('click')
    await wrapper.get('textarea').setValue('  检查文本  ')
    await wrapper.get('textarea').trigger('keydown', {
      key: 'Enter',
      [modifier]: true
    })

    expect(wrapper.emitted('submit-text')?.[0]).toEqual(['检查文本'])
  })

  it('preserves the text draft while switching input modes', async () => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-mode="text"]').trigger('click')
    await wrapper.get('textarea').setValue('草稿')
    await wrapper.get('[data-mode="file"]').trigger('click')
    await wrapper.get('[data-mode="text"]').trigger('click')

    expect(wrapper.get('textarea').element).toHaveProperty('value', '草稿')
  })

  it('accepts all seven formats and the exact 25 MiB boundary', async () => {
    const wrapper = mount(SourceInputPanel)
    const files = [
      'sample.docx',
      'sample.doc',
      'sample.pdf',
      'sample.txt',
      'sample.rtf',
      'sample.md',
      'sample.csv'
    ].map((name) => new File(['ok'], name))
    files.push(
      new File([new Uint8Array(25 * 1024 * 1024)], 'limit.txt')
    )

    for (const file of files) {
      await wrapper.get('[data-dropzone]').trigger('drop', {
        dataTransfer: { files: [file] }
      })
    }

    expect(wrapper.emitted('submit-file')?.map(([file]) => file)).toEqual(files)
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })

  it('rejects unsupported files and files over 25 MiB deterministically', async () => {
    const wrapper = mount(SourceInputPanel)

    await wrapper.get('[data-dropzone]').trigger('drop', {
      dataTransfer: { files: [new File(['MZ'], 'sample.exe')] }
    })
    const formatError = wrapper.get('[role="alert"]').text()
    for (const format of ['DOCX', 'DOC', 'PDF', 'TXT', 'RTF', 'MD', 'CSV']) {
      expect(formatError).toContain(format)
    }

    await wrapper.get('[data-dropzone]').trigger('drop', {
      dataTransfer: {
        files: [
          new File(
            [new Uint8Array(25 * 1024 * 1024 + 1)],
            'oversized.txt'
          )
        ]
      }
    })
    expect(wrapper.get('[role="alert"]').text()).toContain('25 MiB')
    expect(wrapper.emitted('submit-file')).toBeUndefined()
  })

  it.each(['Enter', ' '])(
    'opens the file picker from the keyboard with %s',
    async (key) => {
      const wrapper = mount(SourceInputPanel)
      const input = wrapper.get('input[type="file"]')
      const click = vi.spyOn(input.element as HTMLInputElement, 'click')

      await wrapper.get('[data-dropzone]').trigger('keydown', { key })

      expect(click).toHaveBeenCalledTimes(1)
    }
  )

  it('exposes one visible focusable upload action and hides the native picker from tab order', () => {
    const wrapper = mount(SourceInputPanel)
    const dropzone = wrapper.get('[data-dropzone]')
    const input = wrapper.get('input[type="file"]')

    expect(dropzone.attributes('role')).toBe('button')
    expect(dropzone.attributes('tabindex')).toBe('0')
    expect(dropzone.attributes('aria-label')).toBe(
      '选择或拖放待检查文件'
    )
    expect(input.attributes('hidden')).toBeDefined()
    expect(input.attributes('tabindex')).toBe('-1')
    expect(input.attributes('aria-hidden')).toBe('true')
    expect(dropzone.find('input[type="file"]').exists()).toBe(false)
  })
})
