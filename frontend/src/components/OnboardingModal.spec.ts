import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'

const { sparklesIconStub, gitMergeIconStub, calendarIconStub } = vi.hoisted(() => ({
  sparklesIconStub: {
    name: 'SparklesOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--SparklesOutline' })
    },
  },
  gitMergeIconStub: {
    name: 'GitMergeOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--GitMergeOutline' })
    },
  },
  calendarIconStub: {
    name: 'CalendarClearOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--CalendarClearOutline' })
    },
  },
}))

const messages: Record<string, string> = {
  'onboarding.actions.closeOnboarding': 'Close onboarding',
  'onboarding.welcome.heading': '让 AI 执行需求，生成代码并发起 MR。',
  'onboarding.welcome.body': 'Codify 支持 <strong>任务调度</strong> 与 <u>排队执行</u>，让 AI 在有限计算资源下持续产出代码并发起 <strong>MR</strong>。',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => messages[key] ?? key,
  }),
}))

vi.mock('@vicons/ionicons5', () => ({
  SparklesOutline: sparklesIconStub,
  GitMergeOutline: gitMergeIconStub,
  CalendarClearOutline: calendarIconStub,
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
  NIcon: {
    name: 'NIcon',
    setup(_props: any, { slots }: any) {
      return () => h('i', { class: 'n-icon' }, slots.default?.())
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

  it('renders emphasized markup in the welcome copy', () => {
    const wrapper = mountComponent()

    expect(wrapper.find('.onboarding-modal__section-text strong').text()).toBe('任务调度')
    expect(wrapper.find('.onboarding-modal__section-text u').text()).toBe('排队执行')
    expect(wrapper.findAll('.onboarding-modal__section-text strong')[1].text()).toBe('MR')
  })

  it('renders decorative motif icons as full-size background shapes', () => {
    const wrapper = mountComponent()
    const motifs = wrapper.findAll('[data-testid="onboarding-background-motif"]')
    const motifIcons = wrapper.findAll('.onboarding-modal__motif-icon')

    expect(motifs).toHaveLength(3)
    expect(motifIcons).toHaveLength(3)
    expect(motifs[0].find('.onboarding-modal__motif-icon').exists()).toBe(true)
    expect(motifs[1].find('.onboarding-modal__motif-icon').exists()).toBe(true)
    expect(motifs[2].find('.onboarding-modal__motif-icon').exists()).toBe(true)
    expect(wrapper.find('.icon-stub--SparklesOutline').exists()).toBe(true)
    expect(wrapper.find('.icon-stub--GitMergeOutline').exists()).toBe(true)
    expect(wrapper.find('.icon-stub--CalendarClearOutline').exists()).toBe(true)
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

  it('resets to the first step when reopened', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.workflow.title')

    await wrapper.setProps({ show: false })
    await wrapper.setProps({ show: true })

    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.welcome.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('1')
  })

  it('uses a localized accessibility label for the close button', () => {
    const wrapper = mountComponent()

    expect(wrapper.find('.onboarding-modal__close').attributes('aria-label')).toBe('Close onboarding')
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
