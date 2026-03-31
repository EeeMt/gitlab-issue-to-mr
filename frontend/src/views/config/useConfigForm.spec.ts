import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import {
  provideConfigForm
} from './useConfigForm'

// Mock API
const { mockApi, resetMockApi } = vi.hoisted(() => {
  const mock = {
    getConfig: vi.fn(),
    updateConfig: vi.fn(),
    resetConfig: vi.fn(),
    resetConfigKey: vi.fn()
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => {
      if (typeof fn.mock !== 'undefined') {
        fn.mockReset()
      }
    })
  }
  return { mockApi: mock, resetMockApi }
})

vi.mock('../../api', () => ({
  getConfig: mockApi.getConfig,
  updateConfig: mockApi.updateConfig,
  resetConfig: mockApi.resetConfig,
  resetConfigKey: mockApi.resetConfigKey
}))

// Mock naive-ui - must be hoisted to run before module imports
vi.mock('naive-ui', () => ({
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }),
  useI18n: () => ({
    t: (key: string) => key
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

const mockConfig = {
  runtime: {
    max_concurrency: 5,
    task_timeout: 3600,
    scheduler_interval: 10,
    default_target_branch: 'develop',
    max_retries: 3,
    retry_delay: 120,
    alert_on_failure: true,
    alert_webhook_url_configured: true,
    anthropic_base_url: 'https://api.anthropic.com',
    anthropic_api_key_configured: true,
    anthropic_model: 'claude-3-5-sonnet',
    claude_max_turns: 10,
    allow_monitor_for_users: true,
    allow_schedule_overview_for_users: false,
    allow_analytics_for_users: false,
    allow_oidc_diagnostics_for_users: false
  },
  auth: {
    oidc_enabled: true,
    oidc_issuer_url: 'https://gitlab.example.com',
    oidc_client_id: 'test-client-id',
    oidc_redirect_uri: 'https://app.example.com/api/auth/callback',
    session_cookie_name: 'session',
    session_ttl_seconds: 86400,
    cookie_secure: true,
    cookie_samesite: 'strict',
    auth_admin_usernames: 'admin',
    auth_admin_gitlab_groups: 'developers',
    oidc_client_secret_configured: true
  },
  integration: {
    gitlab_url: 'https://gitlab.example.com',
    gitlab_bot_token_configured: true,
    gitlab_admin_token_configured: false,
    gitlab_webhook_secret_configured: false
  }
}

// Helper component to test useConfigForm within provider context
const TestComponent = defineComponent({
  setup() {
    const configForm = provideConfigForm()
    return { configForm }
  },
  template: '<div>{{ configForm.formValue.value.max_concurrency }}</div>'
})

describe('useConfigForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetMockApi()
  })

  describe('initial state', () => {
    it('should have default form values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      expect(configForm.formValue.value.max_concurrency).toBe(3)
      expect(configForm.formValue.value.task_timeout).toBe(1800)
      expect(configForm.formValue.value.scheduler_interval).toBe(5)
      expect(configForm.formValue.value.default_target_branch).toBe('main')
      expect(configForm.formValue.value.max_retries).toBe(0)
      expect(configForm.formValue.value.retry_delay).toBe(60)
      expect(configForm.formValue.value.alert_on_failure).toBe(false)
      expect(configForm.formValue.value.oidc_enabled).toBe(false)
      expect(configForm.formValue.value.gitlab_url).toBe('')
    })

    it('should have loading as false initially', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      expect(configForm.loading.value).toBe(false)
      expect(configForm.pageActionLoading.value).toBe(false)
    })

    it('should have all sectionSaving flags as false initially', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      expect(configForm.sectionSaving.runtime).toBe(false)
      expect(configForm.sectionSaving.sharedPages).toBe(false)
      expect(configForm.sectionSaving.gitlab).toBe(false)
      expect(configForm.sectionSaving.oidc).toBe(false)
      expect(configForm.sectionSaving.session).toBe(false)
    })
  })

  describe('syncForm', () => {
    it('should sync form values from config', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.formValue.value.max_concurrency).toBe(5)
      expect(configForm.formValue.value.task_timeout).toBe(3600)
      expect(configForm.formValue.value.scheduler_interval).toBe(10)
      expect(configForm.formValue.value.default_target_branch).toBe('develop')
      expect(configForm.formValue.value.max_retries).toBe(3)
      expect(configForm.formValue.value.retry_delay).toBe(120)
      expect(configForm.formValue.value.alert_on_failure).toBe(true)
    })

    it('should sync auth values from config', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.formValue.value.oidc_enabled).toBe(true)
      expect(configForm.formValue.value.oidc_issuer_url).toBe('https://gitlab.example.com')
      expect(configForm.formValue.value.oidc_client_id).toBe('test-client-id')
      expect(configForm.formValue.value.session_cookie_name).toBe('session')
      expect(configForm.formValue.value.session_ttl_seconds).toBe(86400)
    })

    it('should sync integration values from config', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.formValue.value.gitlab_url).toBe('https://gitlab.example.com')
      expect(configForm.formValue.value.gitlab_bot_token_configured).toBe(true)
      expect(configForm.formValue.value.gitlab_admin_token_configured).toBe(false)
    })

    it('should reset lastLoadedValue after sync', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.formValue.value.max_concurrency = 999
      configForm.syncForm(mockConfig)

      expect(configForm.lastLoadedValue.value.max_concurrency).toBe(5)
    })

    it('should clear password inputs after sync', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.formValue.value.alert_webhook_url_input).toBe('')
      expect(configForm.formValue.value.gitlab_bot_token_input).toBe('')
      expect(configForm.formValue.value.gitlab_admin_token_input).toBe('')
      expect(configForm.formValue.value.gitlab_webhook_secret_input).toBe('')
      expect(configForm.formValue.value.oidc_client_secret_input).toBe('')
    })
  })

  describe('isSectionDirty', () => {
    it('should return false when section has not changed', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.isSectionDirty('runtime')).toBe(false)
      expect(configForm.isSectionDirty('gitlab')).toBe(false)
      expect(configForm.isSectionDirty('oidc')).toBe(false)
    })

    it('should return true when runtime section has changed', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.max_concurrency = 10

      expect(configForm.isSectionDirty('runtime')).toBe(true)
    })

    it('should return true when gitlab section has changed', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.gitlab_url = 'https://other.example.com'

      expect(configForm.isSectionDirty('gitlab')).toBe(true)
    })

    it('should return true when oidc section has changed', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.oidc_enabled = false

      expect(configForm.isSectionDirty('oidc')).toBe(true)
    })
  })

  describe('resetSection', () => {
    it('should reset runtime section to last loaded values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.max_concurrency = 999
      configForm.formValue.value.task_timeout = 9999

      configForm.resetSection('runtime')

      expect(configForm.formValue.value.max_concurrency).toBe(5)
      expect(configForm.formValue.value.task_timeout).toBe(3600)
    })

    it('should reset gitlab section to last loaded values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.gitlab_url = 'https://changed.example.com'

      configForm.resetSection('gitlab')

      expect(configForm.formValue.value.gitlab_url).toBe('https://gitlab.example.com')
    })
  })

  describe('isDirty computed', () => {
    it('should return false when no sections are dirty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      expect(configForm.isDirty.value).toBe(false)
    })

    it('should return true when any section is dirty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.max_concurrency = 10

      expect(configForm.isDirty.value).toBe(true)
    })
  })

  describe('handleSaveSection', () => {
    it('should call updateConfig with correct payload for runtime', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      configForm.syncForm(mockConfig)
      configForm.formValue.value.max_concurrency = 10

      await configForm.handleSaveSection('runtime')

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        runtime: expect.objectContaining({
          max_concurrency: 10,
          task_timeout: 3600,
          scheduler_interval: 10
        })
      })
    })

    it('should set sectionSaving to true during save', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      mockApi.updateConfig.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(mockConfig), 100)))

      configForm.syncForm(mockConfig)
      configForm.formValue.value.max_concurrency = 10

      const savePromise = configForm.handleSaveSection('runtime')
      expect(configForm.sectionSaving.runtime).toBe(true)

      await savePromise
      expect(configForm.sectionSaving.runtime).toBe(false)
    })
  })

  describe('buildSectionPayload', () => {
    it('should build correct payload for runtime section', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      configForm.syncForm(mockConfig)

      const payload = configForm.buildRuntimeSectionUpdate()

      expect(payload).toEqual(expect.objectContaining({
        max_concurrency: 5,
        task_timeout: 3600,
        scheduler_interval: 10,
        default_target_branch: 'develop',
        max_retries: 3,
        retry_delay: 120,
        alert_on_failure: true
      }))
    })

    it('should build correct payload for sharedPages section', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      configForm.syncForm(mockConfig)

      const payload = configForm.buildSharedPagesSectionUpdate()

      expect(payload).toEqual({
        allow_monitor_for_users: true,
        allow_schedule_overview_for_users: false,
        allow_analytics_for_users: false,
        allow_oidc_diagnostics_for_users: false
      })
    })

    it('should build correct payload for gitlab section', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      configForm.syncForm(mockConfig)
      configForm.formValue.value.gitlab_bot_token_input = 'new-token'

      const payload = configForm.buildGitlabSectionUpdate()

      expect(payload).toEqual({
        gitlab_url: 'https://gitlab.example.com',
        gitlab_bot_token: 'new-token'
      })
    })

    it('should build correct payload for oidc section', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm
      configForm.syncForm(mockConfig)

      const payload = configForm.buildOidcSectionUpdate()

      expect(payload).toEqual({
        oidc_enabled: true,
        oidc_issuer_url: 'https://gitlab.example.com',
        oidc_client_id: 'test-client-id',
        oidc_redirect_uri: 'https://app.example.com/api/auth/callback'
      })
    })
  })
})

describe('provideConfigForm / useConfigForm', () => {
  it('should provide and inject same instance', async () => {
    const wrapper = mount(defineComponent({
      components: { TestComponent },
      template: '<TestComponent />'
    }))

    await flushPromises()
    expect(wrapper.text()).toBe('3')
  })
})
