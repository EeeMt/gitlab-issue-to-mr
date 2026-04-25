import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import Config from './Config.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------

const { mockGetConfig, mockRouteQuery } = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  // Plain object so the immediate watcher reads the right value during component setup
  mockRouteQuery: { tab: undefined as string | undefined }
}))

vi.mock('../api', () => ({
  getConfig: mockGetConfig,
  updateConfig: vi.fn(),
  resetConfig: vi.fn(),
  resetConfigKey: vi.fn(),
  testOidcConfig: vi.fn(),
  testGitLabConfig: vi.fn(),
  invalidateProjectCache: vi.fn(),
  setupGitLabProjectWebhook: vi.fn(),
  getGitLabProjectWebhookStatus: vi.fn(),
  listGitLabProjectWebhookStatuses: vi.fn(),
  getMattermostNotificationConfig: vi.fn(),
  updateMattermostIntegration: vi.fn(),
  testMattermostIntegration: vi.fn(),
  createMattermostNotificationProfile: vi.fn(),
  updateMattermostNotificationProfile: vi.fn(),
  deleteMattermostNotificationProfile: vi.fn(),
  getPromptTemplates: vi.fn().mockResolvedValue([]),
  getWebhookEvents: vi.fn().mockResolvedValue({ items: [], total: 0 })
}))

vi.mock('vue-router', () => ({
  useRoute: () => ({ query: mockRouteQuery })
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' },
    d: vi.fn((value: unknown) => String(value)),
    n: vi.fn((value: number) => String(value)),
    te: vi.fn((_key: string) => false)
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: ref(1200) }))
}))

vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin--loading' : 'n-spin' }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'wrap'],
    setup(_p: any, { slots }: any) { return () => h('div', slots.default?.()) }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-grid' }, slots.default?.()) }
  },
  NGi: {
    name: 'NGi',
    props: [],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-gi' }, slots.default?.()) }
  },
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'animated'],
    emits: ['update:value'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tabs' }, slots.default?.()) }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: 'n-tab-pane', 'data-name': props.name }, slots.default?.())
    }
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-tag' }, slots.default?.()) }
  },
  NButton: {
    name: 'NButton',
    props: ['loading', 'type'],
    emits: ['click'],
    setup(_p: any, { slots, emit }: any) {
      return () => h('button', { class: 'n-button', onClick: () => emit('click') }, slots.default?.())
    }
  },
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  })
}))

// ---------------------------------------------------------------------------
// Mock data – Config uses the nested { runtime, auth, integration } shape
// ---------------------------------------------------------------------------

const mockConfig = {
  runtime: {
    max_concurrency: 4,
    task_timeout: 3600,
    scheduler_interval: 60,
    default_target_branch: 'main',
    max_retries: 3,
    retry_delay: 300,
    alert_on_failure: false,
    alert_webhook_url_configured: false,
    anthropic_base_url: 'https://api.anthropic.com',
    anthropic_api_key_configured: true,
    anthropic_model: 'claude-3-5-sonnet-20241022',
    claude_max_turns: 20,
    allow_monitor_for_users: true,
    allow_schedule_overview_for_users: false,
    allow_analytics_for_users: true,
    allow_oidc_diagnostics_for_users: false,
    worker_volume_mounts: '',
    worker_environment_variables: [],
    maven_cache_host_path: '',
    maven_settings_host_path: ''
  },
  auth: {
    oidc_enabled: true,
    oidc_issuer_url: 'https://gitlab.example.com',
    oidc_client_id: 'client-id',
    oidc_redirect_uri: 'https://app.example.com/callback',
    session_cookie_name: 'session',
    session_ttl_seconds: 86400,
    cookie_secure: true,
    cookie_samesite: 'Lax',
    auth_admin_usernames: 'admin1,admin2',
    auth_admin_gitlab_groups: '',
    oidc_client_secret_configured: true
  },
  integration: {
    gitlab_url: 'https://gitlab.example.com',
    gitlab_bot_token_configured: true,
    gitlab_admin_token_configured: false,
    gitlab_webhook_secret_configured: true
  }
}

// ---------------------------------------------------------------------------
// Global stubs for all panel components
// ---------------------------------------------------------------------------

const globalStubs = {
  RuntimeSettingsPanel: { template: '<div class="runtime-panel">Runtime</div>' },
  GitLabSettingsPanel: {
    template: '<div class="gitlab-panel">GitLab</div>',
    methods: { fetchWebhookStatuses: () => {} }
  },
  AuthSettingsPanel: { template: '<div class="auth-panel">Auth</div>' },
  MaintenancePanel: { template: '<div class="maintenance-panel">Maintenance</div>' },
  PromptTemplatesPanel: {
    template: '<div class="prompt-panel">Prompts</div>',
    methods: { fetchPromptTemplates: () => {} }
  },
  MattermostNotificationsPanel: { template: '<div class="mattermost-panel">Mattermost</div>' },
  WorkerSettingsPanel: { template: '<div class="worker-panel">Worker</div>' },
  AIProvidersPanel: { template: '<div class="ai-providers-panel">AI Providers</div>' },
  WebhookEventsPanel: { template: '<div class="webhook-events-panel">Webhook Events</div>' },
  PageHeader: { template: '<div class="page-header"><slot name="actions"/></div>' },
  SummaryCard: {
    props: ['label', 'value'],
    template: '<div class="summary-card">{{ label }}: {{ value }}</div>'
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Config', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    vi.clearAllMocks()
    mockGetConfig.mockResolvedValue(mockConfig)
    mockRouteQuery.tab = undefined
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  it('renders config page', async () => {
    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.find('.config-page').exists()).toBe(true)
  })

  it('calls getConfig on mount', async () => {
    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(mockGetConfig).toHaveBeenCalledTimes(1)
  })

  it('shows runtime tab by default', async () => {
    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.activeConfigTab).toBe('runtime')
  })

  it('switches tab when activeConfigTab changes', async () => {
    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    wrapper.vm.activeConfigTab = 'auth'
    await nextTick()

    expect(wrapper.vm.activeConfigTab).toBe('auth')
  })

  it('selects tab from route.query.tab = "gitlab"', async () => {
    // Set BEFORE mounting — the watcher is { immediate: true } so it fires on setup
    mockRouteQuery.tab = 'gitlab'

    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.activeConfigTab).toBe('gitlab')
  })

  it('selects tab from route.query.tab = "auth"', async () => {
    mockRouteQuery.tab = 'auth'

    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    expect(wrapper.vm.activeConfigTab).toBe('auth')
  })

  it('ignores invalid route.query.tab values', async () => {
    mockRouteQuery.tab = 'nonexistent-tab'

    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    // Should remain on the default tab
    expect(wrapper.vm.activeConfigTab).toBe('runtime')
  })

  it('renders tabs in the configured order', async () => {
    wrapper = mount(Config, { global: { stubs: globalStubs } })
    await flushPromises()

    const tabNames = wrapper.findAll('.n-tab-pane').map((pane) => pane.attributes('data-name'))

    expect(tabNames).toEqual([
      'runtime',
      'auth',
      'gitlab',
      'ai-providers',
      'prompt-templates',
      'worker',
      'notifications',
      'maintenance',
      'webhook-events'
    ])
  })
})
