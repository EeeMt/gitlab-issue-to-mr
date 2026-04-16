import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('naive-ui', () => ({
  NModal: {
    name: 'NModal',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-modal' }, slots.default?.()) : null
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('section', { class: 'n-card' }, [slots.header?.(), slots.default?.(), slots.action?.()])
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'secondary', 'ghost'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: ['n-button', props.type ? `n-button--${props.type}` : '', props.secondary ? 'n-button--secondary' : '', props.ghost ? 'n-button--ghost' : ''],
        onClick: () => emit('click'),
      }, slots.default?.())
    },
  },
  NSteps: {
    name: 'NSteps',
    props: ['current'],
    setup(props: any, { slots }: any) {
      return () => h('ol', { class: 'n-steps', 'data-current': props.current }, slots.default?.())
    },
  },
  NStep: {
    name: 'NStep',
    props: ['title', 'description'],
    setup(props: any) {
      return () => h('li', { class: 'n-step' }, [
        h('span', { class: 'n-step__title' }, props.title),
        h('span', { class: 'n-step__description' }, props.description),
      ])
    },
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'align', 'wrap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NThing: {
    name: 'NThing',
    props: ['title'],
    setup(props: any, { slots }: any) {
      return () => h('article', { class: 'n-thing' }, [
        h('h3', { class: 'n-thing__title' }, props.title),
        h('div', { class: 'n-thing__content' }, slots.default?.()),
      ])
    },
  },
}))

import OnboardingModal from './OnboardingModal.vue'

function mountComponent() {
  return mount(OnboardingModal, {
    props: {
      show: true,
    },
  })
}

describe('OnboardingModal', () => {
  it('renders the welcome step first', () => {
    const wrapper = mountComponent()

    expect(wrapper.find('.onboarding-modal').exists()).toBe(true)
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.welcome.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('1')
  })

  it('moves between steps', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.concepts.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('2')

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.workflow.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('3')

    await wrapper.find('[data-testid="onboarding-previous"]').trigger('click')
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.concepts.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('2')
  })

  it('emits close when skip is clicked', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-skip"]').trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
  })

  it('emits view-dashboard on final primary action', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-view-dashboard"]').trigger('click')

    expect(wrapper.emitted('view-dashboard')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })

  it('emits create-issue on final secondary action', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-create-issue"]').trigger('click')

    expect(wrapper.emitted('create-issue')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })
})
