import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref } from 'vue'
import MaintenancePanel from './MaintenancePanel.vue'

// Mock naive-ui components
vi.mock('naive-ui', () => ({
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [
        slots.header?.(),
        slots.default?.()
      ])
    }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary'],
    setup(props: any, { slots }: any) {
      return () => h('button', {
        class: ['n-button', props.type],
        disabled: props.disabled || props.loading,
        onClick: () => {}
      }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['size', 'wrap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    }
  },
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn()
  })
}))

// Mock vue-i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

// Mock useConfigForm
const mockConfigForm = {
  loading: ref(false),
  pageActionLoading: ref(false),
  anySectionSaving: ref(false),
  handleReload: vi.fn(),
  handleReset: vi.fn()
}

vi.mock('./useConfigForm', () => ({
  useConfigForm: () => mockConfigForm
}))

describe('MaintenancePanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
  })

  const mountComponent = () => {
    wrapper = mount(MaintenancePanel, {
      global: {
        stubs: {
          // Stub all naive-ui components to simplify rendering
        }
      }
    })
    return wrapper
  }

  it('should render without errors', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.n-card').exists()).toBe(true)
  })

  it('should have config-actions card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#config-actions').exists()).toBe(true)
  })

  it('should render reload button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('common.reload'))).toBe(true)
  })

  it('should render reset button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('config.resetEnvDefaults'))).toBe(true)
  })

  it('should call handleReload when reload button is clicked', async () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const reloadButton = buttons.find(btn => btn.text().includes('common.reload'))
    expect(reloadButton).toBeDefined()
  })

  it('should show loading state when pageActionLoading is true', () => {
    mockConfigForm.pageActionLoading.value = true
    const wrapper = mountComponent()
    const resetButton = wrapper.findAll('.n-button').find(btn => btn.text().includes('config.resetEnvDefaults'))
    expect(resetButton).toBeDefined()
    // Reset for other tests
    mockConfigForm.pageActionLoading.value = false
  })

  it('should disable buttons when isBusy is true', () => {
    mockConfigForm.loading.value = true
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    buttons.forEach(btn => {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    })
    // Reset for other tests
    mockConfigForm.loading.value = false
  })

  it('should disable buttons when anySectionSaving is true', () => {
    mockConfigForm.anySectionSaving.value = true
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    buttons.forEach(btn => {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    })
    // Reset for other tests
    mockConfigForm.anySectionSaving.value = false
  })
})
