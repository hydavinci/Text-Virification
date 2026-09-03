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
      selectedIssueId: firstId,
      selectedIssueState: 'pending',
      visibleIssueIds: [firstId, secondId],
      summary: {
        total: 3,
        pending: 1,
        accepted: 1,
        rejected: 1
      },
      hasConflicts: true,
      conflictIssueIds: [firstId, secondId],
      canUndoLastBatch: true,
      disabled: false,
      ...overrides
    }
  })
}

describe('ReviewActions', () => {
  it('routes selected issue actions through stable ids', async () => {
    const wrapper = mountActions()

    await wrapper.get('[data-action="accept-selected"]').trigger('click')
    await wrapper.get('[data-action="reject-selected"]').trigger('click')
    await wrapper.setProps({ selectedIssueState: 'accepted' })
    await wrapper.get('[data-action="reset-selected"]').trigger('click')

    expect(wrapper.emitted('set-issue-state')).toEqual([
      [firstId, 'accepted'],
      [firstId, 'rejected']
    ])
    expect(wrapper.emitted('undo-issue')).toEqual([[firstId]])
  })

  it('emits visible-filter batch actions and canonical undo without local history', async () => {
    const wrapper = mountActions()

    await wrapper.get('[data-action="accept-batch"]').trigger('click')
    await wrapper.get('[data-action="reject-batch"]').trigger('click')
    await wrapper.get('[data-action="reset-batch"]').trigger('click')
    await wrapper.get('[data-action="undo-batch"]').trigger('click')

    expect(wrapper.emitted('set-visible-state')).toEqual([
      [[firstId, secondId], 'accepted'],
      [[firstId, secondId], 'rejected'],
      [[firstId, secondId], 'pending']
    ])
    expect(wrapper.emitted('undo-batch')).toHaveLength(1)
  })

  it('reflects canonical counts, conflict state, and undo eligibility', () => {
    const wrapper = mountActions()

    expect(wrapper.get('[data-count="pending"]').text()).toBe('1')
    expect(wrapper.get('[data-count="accepted"]').text()).toBe('1')
    expect(wrapper.get('[data-count="rejected"]').text()).toBe('1')
    expect(wrapper.get('[role="alert"]').text()).toContain('2')
    expect(
      wrapper.get('[data-action="undo-batch"]').attributes('disabled')
    ).toBeUndefined()
  })

  it('disables stale individual and batch actions after re-verification is required', () => {
    const wrapper = mountActions({
      selectedIssueId: null,
      visibleIssueIds: [],
      canUndoLastBatch: false,
      disabled: true,
      hasConflicts: false,
      conflictIssueIds: []
    })

    for (const action of [
      'accept-selected',
      'reject-selected',
      'reset-selected',
      'accept-batch',
      'reject-batch',
      'reset-batch',
      'undo-batch'
    ]) {
      expect(
        wrapper.get(`[data-action="${action}"]`).attributes('disabled')
      ).toBeDefined()
    }
  })
})
