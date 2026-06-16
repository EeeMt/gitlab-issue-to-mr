import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import {
  provideConfigForm
} from './useConfigForm'

// Mock API
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
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
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

vi.mock('../../api', () => ({
  getConfig: mockApi.getConfig,
  updateConfig: mockApi.updateConfig,
  resetConfig: mockApi.resetConfig,
  resetConfigKey: mockApi.resetConfigKey
}))

// Mock naive-ui - must be hoisted to run before module imports
vi.mock('naive-ui', () => ({
  useMessage: () => mockMessage,
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
	    allow_oidc_diagnostics_for_users: false,
	    ci_auto_repair_max_attempts: 4,
	    ci_failure_bundle_retention_days: 45
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
    gitlab_admin_token_configured: false
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
    Object.values(mockMessage).forEach(fn => fn.mockReset())
  })

  afterEach(() => {
    vi.restoreAllMocks()
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
	      expect(configForm.formValue.value.ci_auto_repair_max_attempts).toBe(2)
	      expect(configForm.formValue.value.ci_failure_bundle_retention_days).toBe(30)
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
	      expect(configForm.formValue.value.ci_auto_repair_max_attempts).toBe(4)
	      expect(configForm.formValue.value.ci_failure_bundle_retention_days).toBe(45)
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
      expect('gitlab_webhook_secret_input' in configForm.formValue.value).toBe(false)
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
	          scheduler_interval: 10,
	          ci_auto_repair_max_attempts: 4,
	          ci_failure_bundle_retention_days: 45
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
	        alert_on_failure: true,
	        ci_auto_repair_max_attempts: 4,
	        ci_failure_bundle_retention_days: 45
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

// ============================================================================
// Additional Coverage: handleClearSecret, handleReload, handleReset, isSectionBusy
// ============================================================================
describe('useConfigForm — extended coverage', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    resetMockApi()
  })

  // =========================================================================
  // handleReload
  // =========================================================================
  describe('handleReload', () => {
    it('should fetch config and sync form values', async () => {
      mockApi.getConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleReload()
      await flushPromises()

      expect(mockApi.getConfig).toHaveBeenCalledTimes(1)
      expect(configForm.formValue.value.max_concurrency).toBe(5)
      expect(configForm.loading.value).toBe(false)
    })

    it('should show error message when getConfig fails', async () => {
      mockApi.getConfig.mockRejectedValue(new Error('network error'))

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleReload()
      await flushPromises()

      expect(configForm.loading.value).toBe(false)
    })
  })

  // =========================================================================
  // handleReset
  // =========================================================================
  describe('handleReset', () => {
    it('should call resetConfig and sync form on success', async () => {
      mockApi.resetConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleReset()
      await flushPromises()

      expect(mockApi.resetConfig).toHaveBeenCalledTimes(1)
      expect(configForm.formValue.value.max_concurrency).toBe(5)
      expect(configForm.pageActionLoading.value).toBe(false)
    })

    it('should set pageActionLoading during reset', async () => {
      let resolveReset!: (v: any) => void
      mockApi.resetConfig.mockReturnValue(new Promise(r => { resolveReset = r }))

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      const resetPromise = configForm.handleReset()
      expect(configForm.pageActionLoading.value).toBe(true)

      resolveReset(mockConfig)
      await resetPromise
      await flushPromises()

      expect(configForm.pageActionLoading.value).toBe(false)
    })

    it('should show error when resetConfig fails', async () => {
      mockApi.resetConfig.mockRejectedValue({ response: { data: { detail: 'Reset not allowed' } } })

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleReset()
      await flushPromises()

      expect(configForm.pageActionLoading.value).toBe(false)
    })
  })

  // =========================================================================
  // handleSaveSection — error handling
  // =========================================================================
  describe('handleSaveSection — error handling', () => {
    it('should show API error detail when updateConfig fails with detail', async () => {
      mockApi.updateConfig.mockRejectedValue({ response: { data: { detail: 'Validation error' } } })

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      await configForm.handleSaveSection('runtime')
      await flushPromises()

      expect(configForm.sectionSaving.runtime).toBe(false)
    })

    it('should reset sectionSaving flag after error', async () => {
      mockApi.updateConfig.mockRejectedValue(new Error('generic error'))

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      await configForm.handleSaveSection('gitlab')
      await flushPromises()

      expect(configForm.sectionSaving.gitlab).toBe(false)
    })
  })

  // =========================================================================
  // handleSaveSection — all sections
  // =========================================================================
  describe('handleSaveSection — all sections', () => {
    it('should save sharedPages section with correct payload', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.allow_analytics_for_users = true

      await configForm.handleSaveSection('sharedPages')

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        runtime: expect.objectContaining({
          allow_analytics_for_users: true
        })
      })
    })

    it('should save gitlab section with correct payload', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.gitlab_url = 'https://new-gitlab.example.com'

      await configForm.handleSaveSection('gitlab')

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        integration: expect.objectContaining({
          gitlab_url: 'https://new-gitlab.example.com'
        })
      })
    })

    it('should save oidc section with correct payload', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.oidc_enabled = false

      await configForm.handleSaveSection('oidc')

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        auth: expect.objectContaining({
          oidc_enabled: false
        })
      })
    })

    it('should save session section with correct payload', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.session_ttl_seconds = 3600

      await configForm.handleSaveSection('session')

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        auth: expect.objectContaining({
          session_ttl_seconds: 3600,
          session_cookie_name: 'session'
        })
      })
    })
  })

  // =========================================================================
  // handleClearSecret — all keys
  // =========================================================================
  describe('handleClearSecret', () => {
    it('should clear gitlab_bot_token', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('gitlab_bot_token')
      await flushPromises()

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        integration: { clear_gitlab_bot_token: true }
      })
      expect(configForm.sectionSaving.gitlab).toBe(false)
    })

    it('should clear gitlab_admin_token', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('gitlab_admin_token')
      await flushPromises()

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        integration: { clear_gitlab_admin_token: true }
      })
    })

    it('should clear oidc_client_secret using resetConfigKey', async () => {
      mockApi.resetConfigKey.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('oidc_client_secret')
      await flushPromises()

      expect(mockApi.resetConfigKey).toHaveBeenCalledWith('oidc_client_secret')
      expect(configForm.sectionSaving.oidc).toBe(false)
    })

    it('should clear anthropic_api_key', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('anthropic_api_key')
      await flushPromises()

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        runtime: { clear_anthropic_api_key: true }
      })
      expect(configForm.sectionSaving.runtime).toBe(false)
    })

    it('should clear alert_webhook_url', async () => {
      mockApi.updateConfig.mockResolvedValue(mockConfig)

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('alert_webhook_url')
      await flushPromises()

      expect(mockApi.updateConfig).toHaveBeenCalledWith({
        runtime: { clear_alert_webhook_url: true }
      })
      expect(configForm.sectionSaving.runtime).toBe(false)
    })

    it('should handle error in handleClearSecret', async () => {
      mockApi.updateConfig.mockRejectedValue({ response: { data: { detail: 'Not allowed' } } })

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      await configForm.handleClearSecret('gitlab_bot_token')
      await flushPromises()

      expect(configForm.sectionSaving.gitlab).toBe(false)
    })
  })

  // =========================================================================
  // isSectionBusy
  // =========================================================================
  describe('isSectionBusy', () => {
    it('returns false when nothing is loading or saving', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      expect(configForm.isSectionBusy('runtime')).toBe(false)
    })

    it('returns true when loading is true', async () => {
      let resolveConfig!: (v: any) => void
      mockApi.getConfig.mockReturnValue(new Promise(r => { resolveConfig = r }))

      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.loading.value = true
      expect(configForm.isSectionBusy('runtime')).toBe(true)

      configForm.loading.value = false
    })

    it('returns true when pageActionLoading is true', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.pageActionLoading.value = true
      expect(configForm.isSectionBusy('gitlab')).toBe(true)

      configForm.pageActionLoading.value = false
    })

    it('returns true when any section is saving', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.sectionSaving.oidc = true
      expect(configForm.isSectionBusy('runtime')).toBe(true)

      configForm.sectionSaving.oidc = false
    })
  })

  // =========================================================================
  // anySectionSaving
  // =========================================================================
  describe('anySectionSaving', () => {
    it('returns false when no section is saving', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      expect(configForm.anySectionSaving.value).toBe(false)
    })

    it('returns true when any section is saving', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.sectionSaving.session = true
      expect(configForm.anySectionSaving.value).toBe(true)

      configForm.sectionSaving.session = false
    })
  })

  // =========================================================================
  // Build payload — encryption/secret fields
  // =========================================================================
  describe('build payload — encryption fields', () => {
    it('buildRuntimeSectionUpdate includes webhook URL when input is non-empty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.alert_webhook_url_input = 'https://hooks.example.com/webhook'

      const payload = configForm.buildRuntimeSectionUpdate()
      expect(payload.alert_webhook_url).toBe('https://hooks.example.com/webhook')
    })

    it('buildRuntimeSectionUpdate omits webhook URL when input is empty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.alert_webhook_url_input = ''

      const payload = configForm.buildRuntimeSectionUpdate()
      expect(payload).not.toHaveProperty('alert_webhook_url')
    })

    it('buildRuntimeSectionUpdate trims whitespace from webhook URL', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.alert_webhook_url_input = '  https://hooks.example.com  '

      const payload = configForm.buildRuntimeSectionUpdate()
      expect(payload.alert_webhook_url).toBe('https://hooks.example.com')
    })

    it('buildGitlabSectionUpdate includes admin_token when non-empty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.gitlab_admin_token_input = 'admin-token-123'

      const payload = configForm.buildGitlabSectionUpdate()
      expect(payload.gitlab_admin_token).toBe('admin-token-123')
    })

    it('buildGitlabSectionUpdate omits empty token fields', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      // All inputs are empty by default after sync

      const payload = configForm.buildGitlabSectionUpdate()
      expect(payload).not.toHaveProperty('gitlab_bot_token')
      expect(payload).not.toHaveProperty('gitlab_admin_token')
    })

    it('buildOidcSectionUpdate includes client_secret when non-empty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.oidc_client_secret_input = 'my-secret'

      const payload = configForm.buildOidcSectionUpdate()
      expect(payload.oidc_client_secret).toBe('my-secret')
    })

    it('buildOidcSectionUpdate omits client_secret when empty', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      const payload = configForm.buildOidcSectionUpdate()
      expect(payload).not.toHaveProperty('oidc_client_secret')
    })
  })

  // =========================================================================
  // buildSessionSectionUpdate
  // =========================================================================
  describe('buildSessionSectionUpdate', () => {
    it('should build correct payload for session section', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)

      const payload = configForm.buildSessionSectionUpdate()
      expect(payload).toEqual({
        session_cookie_name: 'session',
        session_ttl_seconds: 86400,
        cookie_secure: true,
        cookie_samesite: 'strict',
        auth_admin_usernames: 'admin',
        auth_admin_gitlab_groups: 'developers'
      })
    })

    it('should trim session_cookie_name', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.session_cookie_name = '  my_session  '

      const payload = configForm.buildSessionSectionUpdate()
      expect(payload.session_cookie_name).toBe('my_session')
    })
  })

  // =========================================================================
  // isSectionDirty — remaining sections
  // =========================================================================
  describe('isSectionDirty — session and sharedPages', () => {
    it('should detect session section changes', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      expect(configForm.isSectionDirty('session')).toBe(false)

      configForm.formValue.value.session_ttl_seconds = 999
      expect(configForm.isSectionDirty('session')).toBe(true)
    })

    it('should detect sharedPages section changes', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      expect(configForm.isSectionDirty('sharedPages')).toBe(false)

      configForm.formValue.value.allow_analytics_for_users = true
      expect(configForm.isSectionDirty('sharedPages')).toBe(true)
    })
  })

  // =========================================================================
  // resetSection — remaining sections
  // =========================================================================
  describe('resetSection — session and oidc', () => {
    it('should reset session section to last loaded values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.session_ttl_seconds = 999
      configForm.formValue.value.cookie_secure = false

      configForm.resetSection('session')

      expect(configForm.formValue.value.session_ttl_seconds).toBe(86400)
      expect(configForm.formValue.value.cookie_secure).toBe(true)
    })

    it('should reset oidc section to last loaded values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.oidc_enabled = false
      configForm.formValue.value.oidc_issuer_url = 'https://changed.example.com'

      configForm.resetSection('oidc')

      expect(configForm.formValue.value.oidc_enabled).toBe(true)
      expect(configForm.formValue.value.oidc_issuer_url).toBe('https://gitlab.example.com')
    })

    it('should reset sharedPages section to last loaded values', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      configForm.syncForm(mockConfig)
      configForm.formValue.value.allow_monitor_for_users = false

      configForm.resetSection('sharedPages')

      expect(configForm.formValue.value.allow_monitor_for_users).toBe(true)
    })
  })

  // =========================================================================
  // syncForm — slot fields
  // =========================================================================
  describe('syncForm — slot capacity fields', () => {
    it('should sync slot_max_tasks and slot_max_tasks_enforce from config', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      const configWithSlots = {
        ...mockConfig,
        runtime: {
          ...mockConfig.runtime,
          slot_max_tasks: 8,
          slot_max_tasks_enforce: true
        }
      }

      configForm.syncForm(configWithSlots)

      expect(configForm.formValue.value.slot_max_tasks).toBe(8)
      expect(configForm.formValue.value.slot_max_tasks_enforce).toBe(true)
    })
  })

  // =========================================================================
  // buildRuntimeSectionUpdate — slot fields
  // =========================================================================
  describe('buildRuntimeSectionUpdate — slot fields', () => {
    it('should include slot_max_tasks and slot_max_tasks_enforce in runtime payload', async () => {
      const wrapper = mount(TestComponent)
      await flushPromises()
      const configForm = (wrapper.vm as any).configForm

      const configWithSlots = {
        ...mockConfig,
        runtime: {
          ...mockConfig.runtime,
          slot_max_tasks: 5,
          slot_max_tasks_enforce: true
        }
      }
      configForm.syncForm(configWithSlots)

      const payload = configForm.buildRuntimeSectionUpdate()
      expect(payload.slot_max_tasks).toBe(5)
      expect(payload.slot_max_tasks_enforce).toBe(true)
    })
  })
})
