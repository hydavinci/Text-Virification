 import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import SourceInputPanel from '../src/components/workspace/SourceInputPanel.vue'

describe('SourceInputPanel', () => {
  it('replaces the large dropzone with accessible compact file actions', async () => {
    const wrapper = mount(SourceInputPanel)
    const file = new File(['synthetic'], 'compact.txt', { type: 'text/plain' })
    const input = wrapper.get('input[type="file"]')
    Object.defineProperty(input.element, 'files', { value: [file] })
    await input.trigger('change')
    expect(wrapper.find('[data-dropzone]').exists()).toBe(false)
    expect(wrapper.get('[data-selected-file]').text()).toContain('compact.txt')
    expect(wrapper.get('[data-change-file]').attributes('aria-label')).toBe('更换文件')
    await wrapper.get('[data-remove-file]').trigger('click')
    expect(wrapper.find('[data-dropzone]').exists()).toBe(true)
  })
  it('shows recovered file metadata and retries without needing file bytes', async () => {
    const wrapper = mount(SourceInputPanel, {
      props: { recoveredFile: { name: 'restored.pdf', size: 1024 }, recoverable: true }
    })
    expect(wrapper.find('[data-dropzone]').exists()).toBe(false)
    expect(wrapper.get('[data-selected-file]').text()).toContain('restored.pdf')
    await wrapper.get('[data-submit-source]').trigger('click')
    expect(wrapper.emitted('resume-job')).toHaveLength(1)
    expect(wrapper.emitted('submit-file')).toBeUndefined()
  })
  it.each(['scan.png', 'scan.jpg', 'scan.JPEG'])(
    'submits image %s through the normal upload workflow',
    async (name) => {
      const wrapper = mount(SourceInputPanel)
      const file = new File(['image'], name)
      await wrapper.get('[data-dropzone]').trigger('drop', {
        dataTransfer: { files: [file] }
      })
      await wrapper.get('[data-submit-source]').trigger('click')
      expect(wrapper.emitted('submit-file')?.[0]).toEqual([file])
      expect(wrapper.find('[role="alert"]').exists()).toBe(false)
    }
  )

  it.each([
    { modifier: 'ctrlKey', label: 'Ctrl+Enter' },
    { modifier: 'metaKey', label: 'Meta+Enter' }
  ])('submits untouched text with $label', async ({ modifier }) => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-mode="text"]').trigger('click')
    await wrapper.get('textarea').setValue('  \ufeff检查文本  \n')
    await wrapper.get('textarea').trigger('keydown', {
      key: 'Enter',
      [modifier]: true
    })

    expect(wrapper.emitted('submit-text')?.[0]).toEqual([
      '  \ufeff检查文本  \n'
    ])
  })

  it('uses Python-equivalent emptiness and preserves FEFF-only input', async () => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-mode="text"]').trigger('click')
    await wrapper
      .get('textarea')
      .setValue(' \t\r\n\u001c\u001d\u001e\u001f\u0085')
    await wrapper.get('button.btn.primary').trigger('click')

    expect(wrapper.emitted('submit-text')).toBeUndefined()
    expect(wrapper.get('[role="alert"]').text()).toContain('请先输入')

    await wrapper.get('textarea').setValue('\ufeff')
    await wrapper.get('button.btn.primary').trigger('click')

    expect(wrapper.emitted('submit-text')?.[0]).toEqual(['\ufeff'])
  })

  it('removes the UTF-16 maxlength and reports Unicode code points', async () => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-mode="text"]').trigger('click')
    await wrapper.get('textarea').setValue('😀a')

    expect(wrapper.get('textarea').attributes('maxlength')).toBeUndefined()
    expect(wrapper.get('.text-footer').text()).toContain('2 字符')
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
      await wrapper.get('[data-submit-source]').trigger('click')
      await wrapper.get('[data-remove-file]').trigger('click')
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

  it('stages a file without submitting and submits it only after confirmation', async () => {
    const wrapper = mount(SourceInputPanel)
    const file = new File(['document'], 'review.txt')
    await wrapper.get('[data-dropzone]').trigger('drop', {
      dataTransfer: { files: [file] }
    })

    expect(wrapper.emitted('submit-file')).toBeUndefined()
    expect(wrapper.get('[data-selected-file]').text()).toContain('review.txt')
    await wrapper.get('[data-submit-source]').trigger('click')
    expect(wrapper.emitted('submit-file')).toEqual([[file]])
  })

  it('removes a staged file and prevents a stale selection from being submitted', async () => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-dropzone]').trigger('drop', {
      dataTransfer: { files: [new File(['document'], 'review.txt')] }
    })
    await wrapper.get('[data-remove-file]').trigger('click')

    expect(wrapper.find('[data-selected-file]').exists()).toBe(false)
    await wrapper.get('[data-submit-source]').trigger('click')
    expect(wrapper.emitted('submit-file')).toBeUndefined()
  })

  it('locks source switching, removal and submission while busy', async () => {
    const wrapper = mount(SourceInputPanel)
    await wrapper.get('[data-dropzone]').trigger('drop', {
      dataTransfer: { files: [new File(['document'], 'review.txt')] }
    })
    await wrapper.setProps({ busy: true })
    expect(wrapper.get('[data-selected-file]').text()).toContain('正在检查')
    expect(wrapper.get('[data-selected-file]').text()).not.toContain('等待开始检查')
    for (const selector of ['[data-mode="text"]', '[data-remove-file]', '[data-submit-source]']) {
      expect(wrapper.get<HTMLButtonElement>(selector).element.disabled).toBe(true)
    }
    await wrapper.get('[data-submit-source]').trigger('click')
    expect(wrapper.emitted('submit-file')).toBeUndefined()
  })
})
