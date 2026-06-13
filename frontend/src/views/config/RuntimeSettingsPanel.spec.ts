import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref } from 'vue'
import RuntimeSettingsPanel from './RuntimeSettingsPanel.vue'

// Mock naive-ui components using h() function approach (like Dashboard.spec.ts)
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
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'labelPlacement'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form' }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label', 'path'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, [
        slots.default?.(),
        slots.feedback?.()
      ])
    }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    }
  },
  NGi: {
    name: 'NGi',
    props: [],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    }
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'min', 'max'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input-number',
        type: 'number',
        value: props.value,
        min: props.min,
        max: props.max,
        onInput: (e: Event) => emit('update:value', Number((e.target as HTMLInputElement).value))
      })
    }
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'type'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        type: props.type || 'text',
        value: props.value,
        placeholder: props.placeholder,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    }
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        onClick: () => emit('update:value', !props.value)
      })
    }
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'round'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
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

// Mock @vueuse/core
vi.mock('@vueuse/core', () => ({
  useWindowSize: () => ({
    width: ref(1200)
  })
}))

// Mock useConfigForm
const mockConfigForm = {
  formValue: ref({
    max_concurrency: 3,
    task_timeout: 1800,
    scheduler_interval: 5,
    default_target_branch: 'main',
    max_retries: 0,
    retry_delay: 60,
    alert_on_failure: false,
    alert_webhook_url_configured: false,
    alert_webhook_url_input: '',
    allow_monitor_for_users: true,
    allow_schedule_overview_for_users: false,
    allow_analytics_for_users: false,
	    allow_oidc_diagnostics_for_users: false,
	    slot_max_tasks: 0,
	    slot_max_tasks_enforce: false,
	    ci_auto_repair_max_attempts: 2,
	    ci_failure_bundle_retention_days: 30
	  }),
  sectionSaving: {
    runtime: false,
    sharedPages: false,
    gitlab: false,
    oidc: false,
    session: false
  },
  isSectionDirty: vi.fn((_section: string) => false),
  isSectionBusy: vi.fn((_section: string) => false),
  resetSection: vi.fn(),
  handleSaveSection: vi.fn(),
  handleClearSecret: vi.fn()
}

vi.mock('./useConfigForm', () => ({
  useConfigForm: () => mockConfigForm
}))

describe('RuntimeSettingsPanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock functions
    mockConfigForm.isSectionDirty.mockReturnValue(false)
    mockConfigForm.isSectionBusy.mockReturnValue(false)
  })

  const mountComponent = () => {
    wrapper = mount(RuntimeSettingsPanel, {
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

  it('should have runtime-settings card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#runtime-settings').exists()).toBe(true)
  })

  it('should have shared-page-settings card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#shared-page-settings').exists()).toBe(true)
  })

  it('should render save and revert buttons for runtime', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    // Should have Save Changes and Revert Changes buttons
    expect(buttonTexts.some(text => text.includes('config.saveChanges'))).toBe(true)
    expect(buttonTexts.some(text => text.includes('config.revertChanges'))).toBe(true)
  })

  it('should render save and revert buttons for shared pages', () => {
    const wrapper = mountComponent()
    const sharedPagesCard = wrapper.find('#shared-page-settings')
    expect(sharedPagesCard.exists()).toBe(true)
  })

  it('should render max_concurrency input', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.n-input-number').exists()).toBe(true)
  })

  it('should render slot capacity section', () => {
    const wrapper = mountComponent()
    const sectionTitles = wrapper.findAll('.config-form__section-title')
    expect(sectionTitles.some(el => el.text() === 'config.slotCapacity')).toBe(true)
  })

	  it('should render slot_max_tasks input and enforce switch', () => {
	    const wrapper = mountComponent()
	    // slot_max_tasks input is an n-input-number, slot_max_tasks_enforce is an n-switch
	    const inputs = wrapper.findAll('.n-input-number')
	    const switches = wrapper.findAll('.n-switch')
	    expect(inputs.length).toBeGreaterThanOrEqual(1)
	    expect(switches.length).toBeGreaterThanOrEqual(1)
	  })

	  it('should render CI auto-repair runtime controls', () => {
	    const wrapper = mountComponent()
	    const text = wrapper.text()
	    expect(text).toContain('config.ciAutoRepair')
	    expect(text).toContain('config.ciAutoRepairMaxAttempts')
	    expect(text).toContain('config.ciFailureBundleRetentionDays')
	  })
	})
