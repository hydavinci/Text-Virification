import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import ReviewActions from '../src/components/workspace/ReviewActions.vue'

const firstId = '33333333-3333-3333-3333-333333333333'
const secondId = '44444444-4444-4444-4444-444444444444'

function mountActions(
  overrides: Partial<InstanceType<typeof ReviewActions>['$props']> = {}
) {
  return mount(ReviewActions, {
    props: {
      summary: {
        total: 3,
        pending: 1,
        accepted: 1,
        rejected: 1
      },
      hasConflicts: true,
      conflictIssueIds: [firstId, secondId],
      ...overrides
    }
  })
}

describe('ReviewActions', () => {
  it('shows review counts without a menu or action buttons', () => {
    const wrapper = mountActions()

    expect(wrapper.get('[data-count="pending"]').text()).toBe('1')
    expect(wrapper.get('[data-count="accepted"]').text()).toBe('1')
    expect(wrapper.get('[data-count="rejected"]').text()).toBe('1')
    expect(wrapper.find('details').exists()).toBe(false)
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('reflects updated canonical counts', async () => {
    const wrapper = mountActions()

    await wrapper.setProps({
      summary: { total: 3, pending: 0, accepted: 2, rejected: 1 }
    })

    expect(wrapper.get('[data-count="pending"]').text()).toBe('0')
    expect(wrapper.get('[data-count="accepted"]').text()).toBe('2')
    expect(wrapper.get('[data-count="rejected"]').text()).toBe('1')
  })

  it('keeps the conflict alert until conflicts are resolved', async () => {
    const wrapper = mountActions()

    expect(wrapper.get('[role="alert"]').text()).toContain('2')
    await wrapper.setProps({ hasConflicts: false, conflictIssueIds: [] })
    expect(wrapper.find('[role="alert"]').exists()).toBe(false)
  })
})
