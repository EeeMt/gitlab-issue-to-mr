import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h } from 'vue'
import Bootstrap from './Bootstrap.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockMessage, mockValidate } = vi.hoisted(() => {
  return {
    mockMessage: {
      error: vi.fn(),
      success: vi.fn(),
      warning: vi.fn(),
      info: vi.fn()
    },
    mockValidate: vi.fn().mockResolvedValue(undefined)
  }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('axios', () => {
  const mockPost = vi.fn()
  const mockIsAxiosError = vi.fn()
  return {
    default: {
      post: mockPost,
      isAxiosError: mockIsAxiosError
    }
  }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' }
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } }))
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isCompact: { value: false },
    isMobile: { value: false }
  })
}))

vi.mock('../components/LanguageToggle.vue', () => ({
  default: { template: '<div class="language-toggle" />' }
}))

vi.mock('../components/PageHeader.vue', () => ({
  default: {
    template: '<div class="page-header"><slot name="title"/><slot name="actions"/></div>'
  }
}))

// ---------------------------------------------------------------------------
// Naive-UI mock
// ---------------------------------------------------------------------------
vi.mock('naive-ui', () => ({
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-card' }, slots.default?.()) }
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'type', 'placeholder', 'autocomplete', 'showPasswordOn', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit, attrs }: any) {
      return () => h('input', {
        class: 'n-input',
        ...attrs,
        value: props.value,
        type: props.type || 'text',
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'block', 'strong', 'size'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled || props.loading,
        onClick: () => emit('click')
      }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-space' }, slots.default?.()) }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NIcon: {
    name: 'NIcon',
    props: ['size', 'component'],
    setup() { return () => h('span', { class: 'n-icon' }) }
  },
  NText: {
    name: 'NText',
    props: ['depth'],
    setup(_p: any, { slots }: any) { return () => h('span', slots.default?.()) }
  },
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'labelPlacement'],
    setup(_p: any, { slots, expose }: any) {
      expose({ validate: mockValidate, restoreValidation: vi.fn() })
      return () => h('div', { class: 'n-form', 'data-testid': 'bootstrap-form' }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label', 'path', 'showLabel'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-form-item' }, slots.default?.()) }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
import axios from 'axios'

const fillForm = async (wrapper: VueWrapper<any>, overrides: Record<string, string> = {}) => {
  const vals = {
    username: 'adminuser',
    displayName: 'Admin User',
    email: 'admin@example.com',
    password: 'securepassword123',
    confirmPassword: 'securepassword123',
    ...overrides
  }
  await wrapper.find('[data-testid="bootstrap-username-input"]').setValue(vals.username)
  await wrapper.find('[data-testid="bootstrap-display-name-input"]').setValue(vals.displayName)
  await wrapper.find('[data-testid="bootstrap-email-input"]').setValue(vals.email)
  // password and confirmPassword are type=password inputs
  const passwordInputs = wrapper.findAll('input[type="password"]')
  await passwordInputs[0].setValue(vals.password)
  await passwordInputs[1].setValue(vals.confirmPassword)
}

const mountBootstrap = () =>
  mount(Bootstrap, {
    global: {}
  })

describe('Bootstrap', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockValidate.mockResolvedValue(undefined)
    vi.stubGlobal('location', { assign: vi.fn(), href: '' })
    vi.useFakeTimers()
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  // -------------------------------------------------------------------------
  it('renders bootstrap page', () => {
    wrapper = mountBootstrap()
    expect(wrapper.find('[data-testid="bootstrap-page"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-card"]').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('renders form with all required inputs', () => {
    wrapper = mountBootstrap()
    expect(wrapper.find('[data-testid="bootstrap-username-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-display-name-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-email-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-password-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-confirm-password-input"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="bootstrap-submit-button"]').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('calls validate before submitting', async () => {
    ;(axios.post as Mock).mockResolvedValue({ data: { status: 'success', next_path: '/dashboard' } })
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')
    await vi.waitFor(() => expect(mockValidate).toHaveBeenCalled())
  })

  // -------------------------------------------------------------------------
  it('calls axios.post with correct payload on submit', async () => {
    ;(axios.post as Mock).mockResolvedValue({ data: { status: 'success', next_path: '/dashboard' } })
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith('/api/auth/local/register', {
        username: 'adminuser',
        display_name: 'Admin User',
        email: 'admin@example.com',
        password: 'securepassword123'
      })
    })
  })

  // -------------------------------------------------------------------------
  it('redirects to next_path on success', async () => {
    ;(axios.post as Mock).mockResolvedValue({ data: { status: 'success', next_path: '/custom' } })
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => expect(mockMessage.success).toHaveBeenCalled())
    vi.runAllTimers()

    expect(window.location.assign).toHaveBeenCalledWith('/custom')
  })

  // -------------------------------------------------------------------------
  it('redirects to /dashboard when no next_path in response', async () => {
    ;(axios.post as Mock).mockResolvedValue({ data: { status: 'success' } })
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => expect(mockMessage.success).toHaveBeenCalled())
    vi.runAllTimers()

    expect(window.location.assign).toHaveBeenCalledWith('/dashboard')
  })

  // -------------------------------------------------------------------------
  it('shows error message on failure with detail', async () => {
    const axiosError = { response: { data: { detail: 'Username already taken' } } }
    ;(axios.isAxiosError as Mock).mockReturnValue(true)
    ;(axios.post as Mock).mockRejectedValue(axiosError)
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('Username already taken')
    })
  })

  // -------------------------------------------------------------------------
  it('shows generic error message on failure without detail', async () => {
    const axiosError = { response: { data: {} } }
    ;(axios.isAxiosError as Mock).mockReturnValue(true)
    ;(axios.post as Mock).mockRejectedValue(axiosError)
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('bootstrap.registrationFailed')
    })
  })

  // -------------------------------------------------------------------------
  it('shows generic error for non-axios errors', async () => {
    ;(axios.isAxiosError as Mock).mockReturnValue(false)
    ;(axios.post as Mock).mockRejectedValue(new Error('Network failure'))
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('bootstrap.registrationFailed')
    })
  })

  // -------------------------------------------------------------------------
  it('does not submit when validation fails', async () => {
    mockValidate.mockRejectedValue([{ field: 'username', message: 'Required' }])
    wrapper = mountBootstrap()
    await fillForm(wrapper)

    await wrapper.find('[data-testid="bootstrap-submit-button"]').trigger('click')

    await vi.waitFor(() => expect(mockValidate).toHaveBeenCalled())
    expect(axios.post).not.toHaveBeenCalled()
  })
})
