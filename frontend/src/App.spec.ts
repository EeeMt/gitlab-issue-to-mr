import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import App from './App.vue'

const {
  mockAuthState,
  mockInitializeAuth,
  mockLogoutAndClearAuth,
  mockSetOnboardingDismissed,
  mockIsAdmin,
  mockDismissedState,
  mockIsMobileState,
} = vi.hoisted(() => ({
  mockAuthState: {
    initialized: true,
    systemInitialized: true,
    loading: false,
    oidcEnabled: true,
    breakGlassEnabled: false,
    breakGlassUsername: null as string | null,
    authenticated: true,
    pagePermissions: {
      monitor: true,
      schedule_overview: true,
      analytics: true,
      oidc_diagnostics: true,
    },
    user: {
      id: 1,
      username: 'tester',
      display_name: 'Test User',
      avatar_url: null,
      platform_role: 'platform_admin',
    },
  },
  mockInitializeAuth: vi.fn(() => Promise.resolve()),
  mockLogoutAndClearAuth: vi.fn(() => Promise.resolve()),
  mockSetOnboardingDismissed: vi.fn(),
  mockIsAdmin: { value: true },
  mockDismissedState: { value: false },
  mockIsMobileState: { value: false },
}))

vi.mock('./auth', () => ({
  authState: mockAuthState,
  canAccessSharedPage: vi.fn(() => true),
  initializeAuth: mockInitializeAuth,
  isAdmin: mockIsAdmin,
  logoutAndClearAuth: mockLogoutAndClearAuth,
}))

vi.mock('./composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: mockIsMobileState,
    isCompact: { value: false },
    width: { value: 1280 },
  }),
}))

vi.mock('./composables/useOnboarding', () => ({
  getOnboardingDismissed: () => mockDismissedState.value,
  setOnboardingDismissed: mockSetOnboardingDismissed,
}))

vi.mock('./components/LanguageToggle.vue', () => ({
  default: {
    name: 'LanguageToggle',
    setup() {
      return () => h('div', { class: 'language-toggle' })
    },
  },
}))

vi.mock('./components/OnboardingModal.vue', () => ({
  default: {
    name: 'OnboardingModal',
    props: ['show'],
    emits: ['close', 'complete', 'view-dashboard', 'create-issue'],
    setup(props: any, { emit }: any) {
      return () => props.show
        ? h('div', { 'data-testid': 'onboarding-modal' }, [
            h('button', { 'data-testid': 'onboarding-close', onClick: () => emit('close') }),
            h('button', { 'data-testid': 'onboarding-complete', onClick: () => emit('complete') }),
            h('button', { 'data-testid': 'onboarding-dashboard', onClick: () => emit('view-dashboard') }),
            h('button', { 'data-testid': 'onboarding-issue', onClick: () => emit('create-issue') }),
          ])
        : null
    },
  },
}))

vi.mock('./i18n', () => ({
  naiveUiLocale: {},
  naiveUiDateLocale: {},
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1280 } })),
}))

vi.mock('@vicons/ionicons5', () => ({
  BarChartOutline: {},
  DocumentTextOutline: {},
  FingerPrintOutline: {},
  GridOutline: {},
  ListOutline: {},
  LogOutOutline: {},
  MenuOutline: {},
  CalendarOutline: {},
  PeopleOutline: {},
  RocketOutline: {},
  SettingsOutline: {},
  SpeedometerOutline: {},
}))

vi.mock('naive-ui', () => ({
  NAvatar: { name: 'NAvatar', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-avatar' }, slots.default?.()) } },
  NButton: { name: 'NButton', emits: ['click'], setup(_props: any, { slots, emit, attrs }: any) { return () => h('button', { ...attrs, class: 'n-button', onClick: () => emit('click') }, slots.default?.()) } },
  NConfigProvider: { name: 'NConfigProvider', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-config-provider' }, slots.default?.()) } },
  NDialogProvider: { name: 'NDialogProvider', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-dialog-provider' }, slots.default?.()) } },
  NDrawer: { name: 'NDrawer', props: ['show'], setup(props: any, { slots }: any) { return () => props.show ? h('div', { class: 'n-drawer' }, slots.default?.()) : null } },
  NDrawerContent: { name: 'NDrawerContent', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-drawer-content' }, slots.default?.()) } },
  NIcon: { name: 'NIcon', setup() { return () => h('i', { class: 'n-icon' }) } },
  NLayout: { name: 'NLayout', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-layout' }, slots.default?.()) } },
  NLayoutSider: { name: 'NLayoutSider', setup(_p: any, { slots }: any) { return () => h('aside', { class: 'n-layout-sider' }, slots.default?.()) } },
  NMenu: { name: 'NMenu', setup() { return () => h('nav', { class: 'n-menu' }) } },
  NMessageProvider: { name: 'NMessageProvider', setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-message-provider' }, slots.default?.()) } },
  NSpin: { name: 'NSpin', setup() { return () => h('div', { class: 'n-spin' }) } },
  NText: { name: 'NText', setup(_p: any, { slots }: any) { return () => h('span', slots.default?.()) } },
}))

function createTestRouter() {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      { path: '/login', name: 'Login', component: { template: '<div data-testid="login-view">Login</div>' } },
      { path: '/bootstrap', name: 'Bootstrap', component: { template: '<div data-testid="bootstrap-view">Bootstrap</div>' } },
      { path: '/dashboard', name: 'Dashboard', component: { template: '<div data-testid="dashboard-view">Dashboard</div>' } },
      { path: '/issues/create', name: 'CreateIssue', component: { template: '<div data-testid="create-issue-view">Create Issue</div>' } },
      { path: '/issues', name: 'Issues', component: { template: '<div>Issues</div>' } },
      { path: '/tasks', name: 'TaskList', component: { template: '<div>Tasks</div>' } },
      { path: '/sessions', name: 'Sessions', component: { template: '<div>Sessions</div>' } },
      { path: '/monitor', name: 'Monitor', component: { template: '<div>Monitor</div>' } },
      { path: '/schedule-overview', name: 'ScheduleOverview', component: { template: '<div>Schedule</div>' } },
      { path: '/analytics', name: 'Analytics', component: { template: '<div>Analytics</div>' } },
      { path: '/configuration', name: 'Config', component: { template: '<div>Config</div>' } },
      { path: '/access-management', name: 'AccessManagement', component: { template: '<div>Access</div>' } },
    ],
  })
}

async function mountAppAt(path: string) {
  const router = createTestRouter()
  await router.push(path)
  await router.isReady()

  const wrapper = mount(App, {
    global: {
      plugins: [router],
    },
  })

  return { wrapper, router }
}

describe('App onboarding integration', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockDismissedState.value = false
    mockIsMobileState.value = false
    mockIsAdmin.value = true
    mockAuthState.initialized = true
    mockAuthState.systemInitialized = true
    mockAuthState.loading = false
    mockAuthState.oidcEnabled = true
    mockAuthState.breakGlassEnabled = false
    mockAuthState.breakGlassUsername = null
    mockAuthState.authenticated = true
    mockAuthState.user = {
      id: 1,
      username: 'tester',
      display_name: 'Test User',
      avatar_url: null,
      platform_role: 'platform_admin',
    }
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('shows onboarding for authenticated users when not dismissed', async () => {
    const { wrapper } = await mountAppAt('/dashboard')

    expect(wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(true)
  })

  it('does not show onboarding when already dismissed', async () => {
    mockDismissedState.value = true

    const { wrapper } = await mountAppAt('/dashboard')

    expect(wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(false)
  })

  it('persists dismissal when onboarding closes or completes', async () => {
    const firstMount = await mountAppAt('/dashboard')
    await firstMount.wrapper.find('[data-testid="onboarding-close"]').trigger('click')

    expect(mockSetOnboardingDismissed).toHaveBeenCalledTimes(1)
    expect(mockSetOnboardingDismissed).toHaveBeenNthCalledWith(1, true)

    firstMount.wrapper.unmount()
    mockSetOnboardingDismissed.mockClear()

    const secondMount = await mountAppAt('/dashboard')
    await secondMount.wrapper.find('[data-testid="onboarding-complete"]').trigger('click')

    expect(mockSetOnboardingDismissed).toHaveBeenCalledTimes(1)
    expect(mockSetOnboardingDismissed).toHaveBeenNthCalledWith(1, true)
  })

  it('routes to dashboard from final CTA', async () => {
    const { wrapper, router } = await mountAppAt('/issues/create')

    await wrapper.find('[data-testid="onboarding-dashboard"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('Dashboard')
    expect(mockSetOnboardingDismissed).toHaveBeenCalledTimes(1)
    expect(mockSetOnboardingDismissed).toHaveBeenCalledWith(true)
  })

  it('routes to create issue from final CTA', async () => {
    const { wrapper, router } = await mountAppAt('/dashboard')

    await wrapper.find('[data-testid="onboarding-issue"]').trigger('click')
    await flushPromises()

    expect(router.currentRoute.value.name).toBe('CreateIssue')
    expect(mockSetOnboardingDismissed).toHaveBeenCalledTimes(1)
    expect(mockSetOnboardingDismissed).toHaveBeenCalledWith(true)
  })

  it('keeps onboarding hidden on login and bootstrap routes', async () => {
    const loginMount = await mountAppAt('/login')
    expect(loginMount.wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(false)
    loginMount.wrapper.unmount()

    const bootstrapMount = await mountAppAt('/bootstrap')
    expect(bootstrapMount.wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(false)
  })
})
