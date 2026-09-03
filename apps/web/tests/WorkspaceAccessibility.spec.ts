import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { afterEach, describe, expect, it } from 'vitest'

import PrivacyDialog from '../src/components/workspace/PrivacyDialog.vue'
import WorkspaceHeader from '../src/components/workspace/WorkspaceHeader.vue'
import appSource from '../src/App.vue?raw'

afterEach(() => {
  document.body.innerHTML = ''
})

describe('workspace accessibility surfaces', () => {
  it('uses keyboard-operable branding and labelled header controls', () => {
    const wrapper = mount(WorkspaceHeader, {
      props: {
        theme: 'light',
        hasResult: false
      }
    })

    expect(wrapper.get('[data-reset-workspace]').element.tagName).toBe('BUTTON')
    expect(wrapper.get('[data-reset-workspace]').attributes('aria-label')).toBe(
      '返回新建检查并清空当前工作区'
    )
    expect(wrapper.get('[data-open-privacy]').attributes('aria-label')).toBe(
      '打开隐私说明'
    )
    expect(wrapper.get('[data-toggle-theme]').attributes('aria-label')).toBe(
      '切换到深色主题'
    )
  })

  it('traps focus, closes on Escape, and restores the opener', async () => {
    const opener = document.createElement('button')
    opener.textContent = 'open'
    document.body.append(opener)
    opener.focus()
    const wrapper = mount(PrivacyDialog, {
      attachTo: document.body,
      props: { open: false }
    })

    await wrapper.setProps({ open: true })
    await nextTick()
    const dialog = wrapper.get('[role="dialog"]')
    const close = wrapper.get<HTMLButtonElement>('[data-close-privacy]')
    const policyLink = wrapper.get<HTMLAnchorElement>('[data-privacy-details]')
    expect(dialog.attributes('aria-modal')).toBe('true')
    expect(document.activeElement).toBe(close.element)

    policyLink.element.focus()
    await dialog.trigger('keydown', { key: 'Tab' })
    expect(document.activeElement).toBe(close.element)

    await dialog.trigger('keydown', { key: 'Escape' })
    expect(wrapper.emitted('close')).toHaveLength(1)
    await wrapper.setProps({ open: false })
    await nextTick()
    expect(document.activeElement).toBe(opener)
  })

  it('globally near-disables animations and transitions for reduced motion', () => {
    expect(appSource).toContain('@media (prefers-reduced-motion: reduce)')
    expect(appSource).toMatch(/animation-duration:\s*\.01ms\s*!important/)
    expect(appSource).toMatch(/transition-duration:\s*\.01ms\s*!important/)
    expect(appSource).toMatch(/transition-delay:\s*0ms\s*!important/)
  })
})
