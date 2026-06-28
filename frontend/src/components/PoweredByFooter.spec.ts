import { describe, expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import PoweredByFooter from './PoweredByFooter.vue'

describe('PoweredByFooter', () => {
  it('shows the short build commit without a hover tooltip', () => {
    const wrapper = mount(PoweredByFooter)
    const expectedVersion = __GIT_COMMIT__ === 'unknown'
      ? 'unknown'
      : __GIT_COMMIT__.slice(0, 7)

    expect(wrapper.text()).toContain('Powered by Codify')
    expect(wrapper.get('.powered-by-footer__version').text()).toBe(expectedVersion)
    expect(wrapper.get('.powered-by-footer__version').attributes('title')).toBeUndefined()
  })
})
