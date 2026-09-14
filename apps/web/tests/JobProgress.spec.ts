import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import JobProgress from '../src/components/JobProgress.vue'

const state = {
  sourceName: 'review.pdf',
  status: 'parsing' as const,
  stage: 'ocr' as const,
  progress: 40,
  message: '正在识别文字',
  failureMessage: null,
  connectionMessage: null
}

describe('JobProgress', () => {
  it('exposes real file progress without technical details', () => {
    const wrapper = mount(JobProgress, { props: { state } })

    expect(wrapper.find('h2, dl').exists()).toBe(false)
    const progress = wrapper.get('progress')
    expect(progress.attributes('aria-label')).toBe('检查进度')
    expect(progress.attributes('value')).toBe('40')
    expect(progress.attributes('max')).toBe('100')
    expect(progress.attributes('aria-valuetext')).toBe('40% · 正在识别文字')
    expect(wrapper.text()).not.toContain('review.pdf')
  })

  it('updates the real percentage, including zero', async () => {
    const wrapper = mount(JobProgress, { props: { state } })
    await wrapper.setProps({ state: { ...state, progress: 0 } })
    expect(wrapper.get('progress').attributes('value')).toBe('0')
    await wrapper.setProps({ state: { ...state, progress: 75 } })
    expect(wrapper.get('progress').attributes('value')).toBe('75')
  })

  it('uses an indeterminate bar when no job percentage is available', () => {
    const wrapper = mount(JobProgress, { props: { state: null } })
    expect(wrapper.get('progress').attributes('value')).toBeUndefined()
    expect(wrapper.get('progress').attributes('aria-valuetext')).toBe('正在检查，请稍候')
  })

  it('shows a connection notice and clears it when progress resumes', async () => {
    const wrapper = mount(JobProgress, {
      props: { state: { ...state, connectionMessage: '连接中断，正在重连' } }
    })
    expect(wrapper.get('[role="status"]').text()).toBe('连接中断，正在重连')
    await wrapper.setProps({ state })
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })

  it('announces failure instead of a stale connection notice', () => {
    const wrapper = mount(JobProgress, {
      props: {
        state: {
          ...state,
          status: 'failed',
          stage: 'failed',
          failureMessage: '检查失败，请重试',
          connectionMessage: '连接中断，正在重连'
        }
      }
    })
    expect(wrapper.get('[role="alert"]').text()).toBe('检查失败，请重试')
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
  })
})
