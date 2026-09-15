import { flushPromises, mount } from '@vue/test-utils'
import { expect, it } from 'vitest'
import { createDefaultAnalyzeOptions } from '../src/api/analyzeOptions'
import { scenarioCatalogKey } from '../src/api/scenarioCatalog'
import WorkspaceSetup from '../src/components/workspace/WorkspaceSetup.vue'
import { scenarioCatalogFixture } from './fixtures/scenarioCatalog'

it('keeps settings accessible while preventing scenario changes during analysis', async () => {
  const wrapper = mount(WorkspaceSetup, {
    props: {
      options: createDefaultAnalyzeOptions(), text: '', busy: true,
      error: null, settingsOpen: false
    },
    global: { provide: { [scenarioCatalogKey as symbol]: async () => scenarioCatalogFixture() } }
  })
  await flushPromises()
  expect(wrapper.get('select[aria-label="文档场景"]').element.matches(':disabled')).toBe(true)
  const opener = wrapper.get('[data-open-settings]')
  expect(opener.element.matches(':disabled')).toBe(false)
  await opener.trigger('click')
  expect(wrapper.emitted('open-settings')).toHaveLength(1)
  expect(wrapper.get('.rule-details').attributes('open')).toBeUndefined()
  await wrapper.setProps({ busy: false })
  await wrapper.get('select[aria-label="文档场景"]').setValue('academic')
  expect(wrapper.emitted('update:options')?.[0]?.[0]).toMatchObject({ scenario: 'academic' })
  wrapper.unmount()
})
