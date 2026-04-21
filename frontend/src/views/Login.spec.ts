import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h } from 'vue'
import Login from './Login.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks (must be declared before any vi.mock calls)
// ---------------------------------------------------------------------------
const { mockAuthState, mockStartLogin, mockBreakGlassLogin, mockMessage, mockRoute } = vi.hoisted(() => {
  return {
    mockAuthState: {
      systemInitialized: true,
      oidcEnabled: true,
      breakGlassEnabled: false,
      breakGlassUsername: null as string | null
    },
    mockStartLogin: vi.fn(),
    mockBreakGlassLogin: vi.fn(),
    mockMessage: {
      error: vi.fn(),
      success: vi.fn(),
      warning: vi.fn(),
      info: vi.fn()
    },
    mockRoute: {
      query: { next: '/dashboard', reason: '' as string }
    }
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

vi.mock('../auth', () => ({
  authState: mockAuthState,
  startLogin: mockStartLogin
}))

vi.mock('../api', () => ({
  breakGlassLogin: mockBreakGlassLogin
}))

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute
}))

vi.mock('../components/LanguageToggle.vue', () => ({
  default: { template: '<div class="language-toggle" />' }
}))

vi.mock('../components/PageHeader.vue', () => ({
  default: {
    template: '<div class="page-header"><slot name="title"/><slot name="actions"/></div>'
  }
}))

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
    props: ['type', 'loading', 'disabled', 'block', 'strong', 'quaternary', 'size', 'secondary'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled || props.loading,
        onClick: () => emit('click')
      }, slots.default?.())
    }
  },
  NTabs: {
    name: 'NTabs',
    props: ['type', 'animated', 'value'],
    emits: ['update:value'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tabs' }, slots.default?.()) }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tab-pane' }, slots.default?.()) }
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
  NCollapseTransition: {
    name: 'NCollapseTransition',
    props: ['show'],
    setup(props: any, { slots }: any) { return () => props.show ? h('div', slots.default?.()) : null }
  },
  NDivider: {
    name: 'NDivider',
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-divider' }, slots.default?.()) }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
import axios from 'axios'

const mountLogin = () =>
  mount(Login, {
    global: {}
  })

describe('Login', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    // Reset authState to "initialized" defaults
    mockAuthState.systemInitialized = true
    mockAuthState.oidcEnabled = true
    mockAuthState.breakGlassEnabled = false
    mockAuthState.breakGlassUsername = null
    // Reset route
    mockRoute.query = { next: '/dashboard', reason: '' }
    // Stub window.location.assign
    vi.stubGlobal('location', { assign: vi.fn(), href: '' })
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.unstubAllGlobals()
  })

  // -------------------------------------------------------------------------
  it('renders login page', () => {
    wrapper = mountLogin()
    expect(wrapper.find('[data-testid="login-page"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="login-card"]').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('shows tabs when systemInitialized is false', () => {
    mockAuthState.systemInitialized = false
    wrapper = mountLogin()
    expect(wrapper.find('.n-tabs').exists()).toBe(true)
    // Both tab panes (local + oidc) should be rendered
    expect(wrapper.findAll('.n-tab-pane').length).toBeGreaterThanOrEqual(2)
  })

  // -------------------------------------------------------------------------
  it('shows GitLab button when systemInitialized is true and oidcEnabled is true', () => {
    mockAuthState.systemInitialized = true
    mockAuthState.oidcEnabled = true
    wrapper = mountLogin()
    // The GitLab button text uses t('login.continueWithGitlab') → returns the key
    expect(wrapper.text()).toContain('login.continueWithGitlab')
  })

  // -------------------------------------------------------------------------
  it('shows localized warning when reason matches a known pattern', () => {
    mockRoute.query = { next: '/dashboard', reason: 'Session expired' }
    wrapper = mountLogin()
    // "expired" maps to the sessionExpired i18n key; the mock t() returns the key itself
    expect(wrapper.text()).toContain('login.redirectReasons.sessionExpired')
  })

  it('shows raw reason string when it does not match any known pattern', () => {
    mockRoute.query = { next: '/dashboard', reason: 'Some unusual error' }
    wrapper = mountLogin()
    // Unknown reasons pass through as-is
    expect(wrapper.text()).toContain('Some unusual error')
  })

  // -------------------------------------------------------------------------
  it('shows error when username is empty', async () => {
    mockAuthState.systemInitialized = false
    wrapper = mountLogin()
    // Leave username empty, fill password
    const passwordInputs = wrapper.findAll('input[type="password"]')
    await passwordInputs[0].setValue('somepassword')
    // Click submit button
    const submitBtn = wrapper.find('[data-testid="login-submit-button"]')
    await submitBtn.trigger('click')
    expect(mockMessage.error).toHaveBeenCalledWith('login.missingCredentials')
  })

  // -------------------------------------------------------------------------
  it('shows error when password is empty', async () => {
    mockAuthState.systemInitialized = false
    wrapper = mountLogin()
    const usernameInput = wrapper.find('[data-testid="login-username-input"]')
    await usernameInput.setValue('admin')
    const submitBtn = wrapper.find('[data-testid="login-submit-button"]')
    await submitBtn.trigger('click')
    expect(mockMessage.error).toHaveBeenCalledWith('login.missingCredentials')
  })

  // -------------------------------------------------------------------------
  it('calls axios.post with correct payload on login', async () => {
    mockAuthState.systemInitialized = false
    ;(axios.post as Mock).mockResolvedValue({ data: { next_path: '/dashboard' } })
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    await wrapper.findAll('input[type="password"]')[0].setValue('password123')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(axios.post).toHaveBeenCalledWith('/api/auth/local/login', {
        username: 'admin',
        password: 'password123',
        next: '/dashboard'
      })
    })
  })

  // -------------------------------------------------------------------------
  it('redirects to next_path on successful login', async () => {
    mockAuthState.systemInitialized = false
    ;(axios.post as Mock).mockResolvedValue({ data: { next_path: '/custom-path' } })
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    await wrapper.findAll('input[type="password"]')[0].setValue('password123')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith('/custom-path')
    })
  })

  // -------------------------------------------------------------------------
  it('redirects to nextTarget when next_path absent from response', async () => {
    mockAuthState.systemInitialized = false
    mockRoute.query = { next: '/my-page', reason: '' }
    ;(axios.post as Mock).mockResolvedValue({ data: {} })
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    await wrapper.findAll('input[type="password"]')[0].setValue('password123')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(window.location.assign).toHaveBeenCalledWith('/my-page')
    })
  })

  // -------------------------------------------------------------------------
  it('shows error message on login failure with axios error detail', async () => {
    mockAuthState.systemInitialized = false
    const axiosError = { response: { data: { detail: 'Invalid credentials' } } }
    ;(axios.isAxiosError as Mock).mockReturnValue(true)
    ;(axios.post as Mock).mockRejectedValue(axiosError)
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    await wrapper.findAll('input[type="password"]')[0].setValue('wrongpassword')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('Invalid credentials')
    })
  })

  // -------------------------------------------------------------------------
  it('shows generic error message on login failure without detail', async () => {
    mockAuthState.systemInitialized = false
    const axiosError = { response: { data: {} } }
    ;(axios.isAxiosError as Mock).mockReturnValue(true)
    ;(axios.post as Mock).mockRejectedValue(axiosError)
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    await wrapper.findAll('input[type="password"]')[0].setValue('wrongpassword')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(mockMessage.error).toHaveBeenCalledWith('login.loginFailed')
    })
  })

  // -------------------------------------------------------------------------
  it('calls startLogin when GitLab button clicked (systemInitialized=true)', async () => {
    mockAuthState.systemInitialized = true
    mockAuthState.oidcEnabled = true
    wrapper = mountLogin()

    // The GitLab button is the first NButton rendered in the systemInitialized=true branch
    const buttons = wrapper.findAll('button')
    const gitlabBtn = buttons.find(b => b.text().includes('login.continueWithGitlab'))
    expect(gitlabBtn).toBeTruthy()
    await gitlabBtn!.trigger('click')

    expect(mockStartLogin).toHaveBeenCalledWith('/dashboard')
  })

  // -------------------------------------------------------------------------
  it('clears password field after login attempt', async () => {
    mockAuthState.systemInitialized = false
    ;(axios.post as Mock).mockResolvedValue({ data: { next_path: '/dashboard' } })
    wrapper = mountLogin()

    await wrapper.find('[data-testid="login-username-input"]').setValue('admin')
    const passwordInput = wrapper.findAll('input[type="password"]')[0]
    await passwordInput.setValue('password123')
    await wrapper.find('[data-testid="login-submit-button"]').trigger('click')

    await vi.waitFor(() => {
      expect(wrapper.vm.localPassword).toBe('')
    })
  })
})
