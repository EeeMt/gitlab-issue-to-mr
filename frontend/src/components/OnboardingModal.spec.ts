import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'

const {
  sparklesIconStub,
  gitMergeIconStub,
  calendarIconStub,
  documentIconStub,
  layersIconStub,
  checkmarkDoneIconStub,
  playIconStub,
  cubeIconStub,
  cogIconStub,
  chevronForwardIconStub,
  optionsIconStub,
} = vi.hoisted(() => ({
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
  documentIconStub: {
    name: 'DocumentTextOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--DocumentTextOutline' })
    },
  },
  layersIconStub: {
    name: 'LayersOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--LayersOutline' })
    },
  },
  checkmarkDoneIconStub: {
    name: 'CheckmarkDoneCircleOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--CheckmarkDoneCircleOutline' })
    },
  },
  playIconStub: {
    name: 'PlayCircleOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--PlayCircleOutline' })
    },
  },
  cubeIconStub: {
    name: 'CubeOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--CubeOutline' })
    },
  },
  cogIconStub: {
    name: 'CogOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--CogOutline' })
    },
  },
  chevronForwardIconStub: {
    name: 'ChevronForwardOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--ChevronForwardOutline' })
    },
  },
  optionsIconStub: {
    name: 'OptionsOutline',
    setup() {
      return () => h('svg', { class: 'icon-stub icon-stub--OptionsOutline' })
    },
  },
}))

const messages: Record<string, string> = {
  'onboarding.actions.closeOnboarding': 'Close onboarding',
  'onboarding.welcome.heading': '让 AI 执行需求，生成代码并发起 MR。',
  'onboarding.welcome.body': 'Codify uses [[scheduling]] to keep AI [[code]] and opening [[mr]] under limited compute capacity.',
  'onboarding.welcome.bodyScheduling': 'task scheduling',
  'onboarding.welcome.bodyCode': 'generating code',
  'onboarding.welcome.bodyMr': 'merge requests',
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
  DocumentTextOutline: documentIconStub,
  LayersOutline: layersIconStub,
  CheckmarkDoneCircleOutline: checkmarkDoneIconStub,
  PlayCircleOutline: playIconStub,
  CubeOutline: cubeIconStub,
  CogOutline: cogIconStub,
  ChevronForwardOutline: chevronForwardIconStub,
  OptionsOutline: optionsIconStub,
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

const stepHeights: Record<number, number> = {
  1: 506,
  2: 462,
  3: 613,
  4: 428,
}

const originalScrollHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight')
const originalOffsetHeightDescriptor = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'offsetHeight')

function resolveRenderedStepNumber(element: HTMLElement): number {
  const explicitStep = Number(element.dataset.measureStep)
  if (explicitStep > 0) {
    return explicitStep
  }

  const shellContent = element.closest('.onboarding-modal-shell__content') as HTMLElement | null
  const current = Number(shellContent?.querySelector('.n-steps')?.getAttribute('data-current'))
  return current > 0 ? current : 1
}

function mountComponent() {
  return mount(OnboardingModal, {
    props: {
      show: true,
    },
  })
}

function getVisibleShellContent(wrapper: ReturnType<typeof mountComponent>) {
  return wrapper.get('.onboarding-modal-shell__content:not([data-measure-step])')
}

function getVisibleShell(wrapper: ReturnType<typeof mountComponent>) {
  return wrapper.get('.onboarding-modal-shell:not(.onboarding-modal-shell--measure)')
}

function getVisibleBackgroundSet(wrapper: ReturnType<typeof mountComponent>) {
  return getVisibleShellContent(wrapper).get('.onboarding-modal__background-set')
}

describe('OnboardingModal', () => {
  beforeEach(() => {
    Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
      configurable: true,
      get() {
        const element = this as HTMLElement

        if (element.classList.contains('onboarding-modal-shell__content')) {
          return stepHeights[resolveRenderedStepNumber(element)] ?? 0
        }

        return 0
      },
    })

    Object.defineProperty(HTMLElement.prototype, 'offsetHeight', {
      configurable: true,
      get() {
        const element = this as HTMLElement
        const inlineHeight = Number.parseFloat(element.style.height || '')
        if (!Number.isNaN(inlineHeight) && inlineHeight > 0) {
          return inlineHeight
        }

        if (element.classList.contains('onboarding-modal-shell')) {
          const visibleContent = element.querySelector('.onboarding-modal-shell__content:not([data-measure-step])') as HTMLElement | null
          return visibleContent?.scrollHeight ?? 0
        }

        return 0
      },
    })
  })

  afterEach(() => {
    if (originalScrollHeightDescriptor) {
      Object.defineProperty(HTMLElement.prototype, 'scrollHeight', originalScrollHeightDescriptor)
    }

    if (originalOffsetHeightDescriptor) {
      Object.defineProperty(HTMLElement.prototype, 'offsetHeight', originalOffsetHeightDescriptor)
    }
  })

  it('renders the welcome step first', () => {
    const wrapper = mountComponent()

    expect(wrapper.find('.onboarding-modal').exists()).toBe(true)
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.welcome.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('1')
  })

  it('renders emphasized welcome copy without html messages', () => {
    const wrapper = mountComponent()
    const visibleShellContent = getVisibleShellContent(wrapper)

    const emphasis = visibleShellContent.findAll('.onboarding-modal__section-text strong')

    expect(visibleShellContent.find('.onboarding-modal__section-text').text()).toContain('Codify uses')
    expect(visibleShellContent.find('.onboarding-modal__section-text u').exists()).toBe(false)
    expect(emphasis).toHaveLength(3)
    expect(emphasis[0].text()).toBe('task scheduling')
    expect(emphasis[1].text()).toBe('generating code')
    expect(emphasis[2].text()).toBe('merge requests')
  })

  it('applies emphasis styling to highlighted welcome segments', () => {
    const wrapper = mountComponent()
    const visibleShellContent = getVisibleShellContent(wrapper)

    const emphasis = visibleShellContent.findAll('.onboarding-modal__section-emphasis')

    expect(emphasis).toHaveLength(3)
    expect(emphasis[0].text()).toBe('task scheduling')
    expect(emphasis[1].text()).toBe('generating code')
    expect(emphasis[2].text()).toBe('merge requests')
  })

  it('shows step-specific motifs tied to the active theme', async () => {
    const wrapper = mountComponent()
    let visibleBackgroundSet = getVisibleBackgroundSet(wrapper)

    expect(visibleBackgroundSet.find('.icon-stub--SparklesOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--GitMergeOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--DocumentTextOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--LayersOutline').exists()).toBe(false)
    expect(visibleBackgroundSet.find('.icon-stub--PlayCircleOutline').exists()).toBe(false)

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    visibleBackgroundSet = getVisibleBackgroundSet(wrapper)

    expect(visibleBackgroundSet.find('.icon-stub--DocumentTextOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--LayersOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--CheckmarkDoneCircleOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--GitMergeOutline').exists()).toBe(false)

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    visibleBackgroundSet = getVisibleBackgroundSet(wrapper)

    expect(visibleBackgroundSet.find('.icon-stub--CogOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--CubeOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--SparklesOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--GitMergeOutline').exists()).toBe(false)

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    visibleBackgroundSet = getVisibleBackgroundSet(wrapper)

    expect(visibleBackgroundSet.find('.icon-stub--CalendarClearOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--PlayCircleOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--GitMergeOutline').exists()).toBe(true)
    expect(visibleBackgroundSet.find('.icon-stub--LayersOutline').exists()).toBe(false)
  })

  it('renders motifs through a single crossfade transition', () => {
    const wrapper = mountComponent()

    expect(wrapper.findComponent({ name: 'TransitionGroup' }).exists()).toBe(false)
    expect(wrapper.findComponent({ name: 'Transition' }).exists()).toBe(true)
    expect(wrapper.find('.onboarding-modal__background-set').exists()).toBe(true)
  })


  it('uses translucent surfaces for concept and architecture cards', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(getVisibleShellContent(wrapper).findAll('.onboarding-modal__surface').length).toBeGreaterThan(0)
    expect(getVisibleShellContent(wrapper).findAll('.concept-flow-card.onboarding-modal__surface')).toHaveLength(3)

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(getVisibleShellContent(wrapper).findAll('.onboarding-modal__pipeline-card.onboarding-modal__surface')).toHaveLength(4)
  })

  it('resets to the first step when reopened', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.architecture.title')

    await wrapper.setProps({ show: false })
    await wrapper.setProps({ show: true })

    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.welcome.title')
    expect(wrapper.find('.n-steps').attributes('data-current')).toBe('1')
  })

  it('updates shell height immediately when navigating into the concepts step', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await vi.waitFor(() => {
      expect(getVisibleShell(wrapper).attributes('style')).toContain('height: 462px')
    })
  })

  it('updates shell height immediately when navigating back into the concepts step', async () => {
    const wrapper = mountComponent()

    await nextTick()
    await nextTick()
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await nextTick()
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await nextTick()
    expect(wrapper.find('[data-testid="onboarding-step-title"]').text()).toBe('onboarding.architecture.title')

    await wrapper.find('[data-testid="onboarding-previous"]').trigger('click')
    await vi.waitFor(() => {
      expect(getVisibleShell(wrapper).attributes('style')).toContain('height: 462px')
    })
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
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-view-dashboard"]').trigger('click')

    expect(wrapper.emitted('view-dashboard')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })

  it('emits create-issue on final secondary action', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-next"]').trigger('click')
    await wrapper.find('[data-testid="onboarding-create-issue"]').trigger('click')

    expect(wrapper.emitted('create-issue')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })
})
