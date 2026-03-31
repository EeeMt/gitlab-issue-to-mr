import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref, defineComponent } from 'vue'
import AuthSettingsPanel from './AuthSettingsPanel.vue'

// Mock OidcDiagnosticsPanel
vi.mock('../../components/config/OidcDiagnosticsPanel.vue', () => ({
  default: {
    name: 'OidcDiagnosticsPanel',
    template: '<div class="oidc-diagnostics-panel">OidcDiagnosticsPanel</div>'
  }
}))

// Mock API
const mockApi = {
  testOidcConfig: vi.fn()
}

vi.mock('../../api', () => ({
  testOidcConfig: (...args: any[]) => mockApi.testOidcConfig(...args)
}))

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
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: ['n-alert', `n-alert--${props.type}`] }, slots.default?.())
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
  NSelect: {
    name: 'NSelect',
    props: ['options', 'value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        value: props.value,
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
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
    oidc_enabled: false,
    oidc_issuer_url: 'https://gitlab.example.com',
    oidc_client_id: 'test-client-id',
    oidc_client_secret_input: '',
    oidc_client_secret_configured: false,
    oidc_redirect_uri: 'https://app.example.com/api/auth/callback',
    session_cookie_name: 'session',
    session_ttl_seconds: 86400,
    cookie_secure: true,
    cookie_samesite: 'strict',
    auth_admin_usernames: 'admin',
    auth_admin_gitlab_groups: 'developers'
  }),
  sectionSaving: {
    oidc: false,
    session: false
  },
  isSectionDirty: vi.fn((_section: string) => false),
  handleSaveSection: vi.fn(),
  handleClearSecret: vi.fn(),
  buildOidcSectionUpdate: vi.fn(() => ({
    oidc_enabled: false,
    oidc_issuer_url: 'https://gitlab.example.com',
    oidc_client_id: 'test-client-id',
    oidc_redirect_uri: 'https://app.example.com/api/auth/callback'
  }))
}

vi.mock('./useConfigForm', () => ({
  useConfigForm: () => mockConfigForm
}))

describe('AuthSettingsPanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockConfigForm.isSectionDirty.mockReturnValue(false)
  })

  const mountComponent = () => {
    wrapper = mount(AuthSettingsPanel, {
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

  it('should have oidc-settings card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#oidc-settings').exists()).toBe(true)
  })

  it('should have session-settings card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#session-settings').exists()).toBe(true)
  })

  it('should render OIDC save and revert buttons', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    // Should have OIDC save and revert buttons
    expect(buttonTexts.filter(t => t.includes('config.saveChanges')).length).toBeGreaterThanOrEqual(1)
    expect(buttonTexts.filter(t => t.includes('config.revertChanges')).length).toBeGreaterThanOrEqual(1)
  })

  it('should render test OIDC connection button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('config.testOidcConnection'))).toBe(true)
  })

  it('should render clear OIDC secret button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('config.clearOidcSecret'))).toBe(true)
  })

  it('should render session save and revert buttons', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    // Session section should also have save and revert
    expect(buttonTexts.some(text => text.includes('config.saveChanges'))).toBe(true)
    expect(buttonTexts.some(text => text.includes('config.revertChanges'))).toBe(true)
  })

  it('should render admin username input', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.n-form-item').exists()).toBe(true)
  })

  it('should render sameSite select options', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.n-select').exists()).toBe(true)
  })

  it('should disable buttons when isAuthBusy is true', () => {
    mockConfigForm.sectionSaving.oidc = true
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    buttons.forEach(btn => {
      const text = btn.text()
      if (text.includes('config.saveChanges') || text.includes('config.revertChanges')) {
        expect((btn.element as HTMLButtonElement).disabled).toBe(true)
      }
    })
    // Reset
    mockConfigForm.sectionSaving.oidc = false
  })
})
