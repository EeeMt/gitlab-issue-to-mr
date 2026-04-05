/**
 * Config Form Composable
 *
 * Shared state and logic for Config page panels.
 * Provides form data management, dirty detection, and section-based saving.
 *
 * Usage:
 * - Parent (Config.vue) calls useConfigForm() once and provides via provide()
 * - Child panels call useConfigForm() to inject the shared state
 */

import { computed, inject, provide, reactive, ref, type ComputedRef, type InjectionKey, type Ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getConfig,
  resetConfig,
  resetConfigKey,
  updateConfig,
  type AuthConfigUpdate,
  type Config,
  type ConfigUpdate,
  type IntegrationConfigUpdate,
  type RuntimeConfigUpdate
} from '../../api'

// ============================================================================
// Types
// ============================================================================

export type ConfigForm = {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
  max_retries: number
  retry_delay: number
  alert_on_failure: boolean
  alert_webhook_url_configured: boolean
  alert_webhook_url_input: string
  allow_monitor_for_users: boolean
  allow_schedule_overview_for_users: boolean
  allow_analytics_for_users: boolean
  allow_oidc_diagnostics_for_users: boolean
  gitlab_url: string
  gitlab_bot_token_configured: boolean
  gitlab_bot_token_input: string
  gitlab_admin_token_configured: boolean
  gitlab_admin_token_input: string
  gitlab_webhook_secret_configured: boolean
  gitlab_webhook_secret_input: string
  oidc_enabled: boolean
  oidc_issuer_url: string
  oidc_client_id: string
  oidc_redirect_uri: string
  session_cookie_name: string
  session_ttl_seconds: number
  cookie_secure: boolean
  cookie_samesite: string
  auth_admin_usernames: string
  auth_admin_gitlab_groups: string
  oidc_client_secret_configured: boolean
  oidc_client_secret_input: string
  slot_max_tasks: number
  slot_max_tasks_enforce: boolean
}

export type ConfigSectionKey = 'runtime' | 'sharedPages' | 'gitlab' | 'oidc' | 'session'

// ============================================================================
// Section Field Mappings
// ============================================================================

export const runtimeSectionFields: readonly (keyof ConfigForm)[] = [
  'max_concurrency',
  'task_timeout',
  'scheduler_interval',
  'default_target_branch',
  'max_retries',
  'retry_delay',
  'alert_on_failure',
  'alert_webhook_url_input',
  'slot_max_tasks',
  'slot_max_tasks_enforce'
]

export const sharedPagesSectionFields: readonly (keyof ConfigForm)[] = [
  'allow_monitor_for_users',
  'allow_schedule_overview_for_users',
  'allow_analytics_for_users',
  'allow_oidc_diagnostics_for_users'
]

export const gitlabSectionFields: readonly (keyof ConfigForm)[] = [
  'gitlab_url',
  'gitlab_bot_token_input',
  'gitlab_admin_token_input',
  'gitlab_webhook_secret_input'
]

export const oidcSectionFields: readonly (keyof ConfigForm)[] = [
  'oidc_enabled',
  'oidc_issuer_url',
  'oidc_client_id',
  'oidc_redirect_uri',
  'oidc_client_secret_input'
]

export const sessionSectionFields: readonly (keyof ConfigForm)[] = [
  'session_cookie_name',
  'session_ttl_seconds',
  'cookie_secure',
  'cookie_samesite',
  'auth_admin_usernames',
  'auth_admin_gitlab_groups'
]

export const sectionFieldKeys: Record<ConfigSectionKey, readonly (keyof ConfigForm)[]> = {
  runtime: runtimeSectionFields,
  sharedPages: sharedPagesSectionFields,
  gitlab: gitlabSectionFields,
  oidc: oidcSectionFields,
  session: sessionSectionFields
}

export const sectionKeys: ConfigSectionKey[] = ['runtime', 'sharedPages', 'gitlab', 'oidc', 'session']

// ============================================================================
// Injection Key
// ============================================================================

export const configFormKey: InjectionKey<ReturnType<typeof createConfigForm>> = Symbol('configForm')

// ============================================================================
// Default Form Values
// ============================================================================

function createDefaultFormValue(): ConfigForm {
  return {
    max_concurrency: 3,
    task_timeout: 1800,
    scheduler_interval: 5,
    default_target_branch: 'main',
    max_retries: 0,
    retry_delay: 60,
    alert_on_failure: false,
    alert_webhook_url_configured: false,
    alert_webhook_url_input: '',
    allow_monitor_for_users: false,
    allow_schedule_overview_for_users: false,
    allow_analytics_for_users: false,
    allow_oidc_diagnostics_for_users: false,
    gitlab_url: '',
    gitlab_bot_token_configured: false,
    gitlab_bot_token_input: '',
    gitlab_admin_token_configured: false,
    gitlab_admin_token_input: '',
    gitlab_webhook_secret_configured: false,
    gitlab_webhook_secret_input: '',
    oidc_enabled: false,
    oidc_issuer_url: '',
    oidc_client_id: '',
    oidc_redirect_uri: '',
    session_cookie_name: 'codify_session',
    session_ttl_seconds: 28800,
    cookie_secure: true,
    cookie_samesite: 'lax',
    auth_admin_usernames: '',
    auth_admin_gitlab_groups: '',
    oidc_client_secret_configured: false,
    oidc_client_secret_input: '',
    slot_max_tasks: 0,
    slot_max_tasks_enforce: false
  }
}

// ============================================================================
// Composable Implementation
// ============================================================================

export interface UseConfigFormReturn {
  // State
  formValue: Ref<ConfigForm>
  lastLoadedValue: Ref<ConfigForm>
  sectionSaving: Record<ConfigSectionKey, boolean>
  loading: Ref<boolean>
  pageActionLoading: Ref<boolean>

  // Computed
  isDirty: ComputedRef<boolean>
  anySectionSaving: ComputedRef<boolean>

  // Section Operations
  isSectionDirty: (section: ConfigSectionKey) => boolean
  isSectionBusy: (_section: ConfigSectionKey) => boolean
  resetSection: (section: ConfigSectionKey) => void

  // Save Operations
  handleSaveSection: (section: ConfigSectionKey) => Promise<void>
  handleClearSecret: (key: 'oidc_client_secret' | 'anthropic_api_key' | 'alert_webhook_url' | 'gitlab_bot_token' | 'gitlab_admin_token' | 'gitlab_webhook_secret') => Promise<void>
  handleReload: () => Promise<void>
  handleReset: () => Promise<void>

  // Internal (for panels that need to trigger state updates)
  syncForm: (config: Config) => void
  buildRuntimeSectionUpdate: () => RuntimeConfigUpdate
  buildSharedPagesSectionUpdate: () => RuntimeConfigUpdate
  buildGitlabSectionUpdate: () => IntegrationConfigUpdate
  buildOidcSectionUpdate: () => AuthConfigUpdate
  buildSessionSectionUpdate: () => AuthConfigUpdate
}

function createConfigForm(): UseConfigFormReturn {
  const message = useMessage()
  const { t } = useI18n()

  // ============================================================================
  // State
  // ============================================================================

  const loading = ref(false)
  const pageActionLoading = ref(false)
  const formValue = ref<ConfigForm>(createDefaultFormValue())
  const lastLoadedValue = ref<ConfigForm>(createDefaultFormValue())

  const sectionSaving = reactive<Record<ConfigSectionKey, boolean>>({
    runtime: false,
    sharedPages: false,
    gitlab: false,
    oidc: false,
    session: false
  })

  // ============================================================================
  // Computed
  // ============================================================================

  const anySectionSaving = computed(() =>
    sectionKeys.some((section) => sectionSaving[section])
  )

  const isDirty = computed(() => sectionKeys.some((section) => isSectionDirty(section)))

  // ============================================================================
  // Helper Functions
  // ============================================================================

  function snapshotSection(section: ConfigSectionKey): Record<string, string | number | boolean> {
    const snapshot: Record<string, string | number | boolean> = {}
    for (const key of sectionFieldKeys[section]) {
      snapshot[key] = formValue.value[key]
    }
    return snapshot
  }

  function isSectionDirty(section: ConfigSectionKey): boolean {
    const current = snapshotSection(section)
    const loaded: Record<string, string | number | boolean> = {}
    for (const key of sectionFieldKeys[section]) {
      loaded[key] = lastLoadedValue.value[key]
    }
    return JSON.stringify(current) !== JSON.stringify(loaded)
  }

  function copyFields<K extends keyof ConfigForm>(keys: readonly K[], source: ConfigForm, target: ConfigForm) {
    for (const key of keys) {
      target[key] = source[key]
    }
  }

  function syncForm(config: Config) {
    formValue.value = {
      max_concurrency: config.runtime.max_concurrency,
      task_timeout: config.runtime.task_timeout,
      scheduler_interval: config.runtime.scheduler_interval,
      default_target_branch: config.runtime.default_target_branch,
      max_retries: config.runtime.max_retries,
      retry_delay: config.runtime.retry_delay,
      alert_on_failure: config.runtime.alert_on_failure,
      alert_webhook_url_configured: config.runtime.alert_webhook_url_configured,
      alert_webhook_url_input: '',
      allow_monitor_for_users: config.runtime.allow_monitor_for_users,
      allow_schedule_overview_for_users: config.runtime.allow_schedule_overview_for_users,
      allow_analytics_for_users: config.runtime.allow_analytics_for_users,
      allow_oidc_diagnostics_for_users: config.runtime.allow_oidc_diagnostics_for_users,
      gitlab_url: config.integration.gitlab_url,
      gitlab_bot_token_configured: config.integration.gitlab_bot_token_configured,
      gitlab_bot_token_input: '',
      gitlab_admin_token_configured: config.integration.gitlab_admin_token_configured,
      gitlab_admin_token_input: '',
      gitlab_webhook_secret_configured: config.integration.gitlab_webhook_secret_configured,
      gitlab_webhook_secret_input: '',
      oidc_enabled: config.auth.oidc_enabled,
      oidc_issuer_url: config.auth.oidc_issuer_url,
      oidc_client_id: config.auth.oidc_client_id,
      oidc_redirect_uri: config.auth.oidc_redirect_uri,
      session_cookie_name: config.auth.session_cookie_name,
      session_ttl_seconds: config.auth.session_ttl_seconds,
      cookie_secure: config.auth.cookie_secure,
      cookie_samesite: config.auth.cookie_samesite,
      auth_admin_usernames: config.auth.auth_admin_usernames,
      auth_admin_gitlab_groups: config.auth.auth_admin_gitlab_groups,
      oidc_client_secret_configured: config.auth.oidc_client_secret_configured,
      oidc_client_secret_input: '',
      slot_max_tasks: config.runtime.slot_max_tasks,
      slot_max_tasks_enforce: config.runtime.slot_max_tasks_enforce
    }
    lastLoadedValue.value = { ...formValue.value }
  }

  function isSectionBusy(_section: ConfigSectionKey): boolean {
    // Note: This is a simplified version. Panels with additional states
    // (like gitlab with webhook statuses) should handle locally or use their own busy state.
    return (
      loading.value ||
      pageActionLoading.value ||
      anySectionSaving.value
    )
  }

  // ============================================================================
  // Build Update Payloads
  // ============================================================================

  function buildRuntimeSectionUpdate(): RuntimeConfigUpdate {
    const update: RuntimeConfigUpdate = {
      max_concurrency: formValue.value.max_concurrency,
      task_timeout: formValue.value.task_timeout,
      scheduler_interval: formValue.value.scheduler_interval,
      default_target_branch: formValue.value.default_target_branch.trim(),
      max_retries: formValue.value.max_retries,
      retry_delay: formValue.value.retry_delay,
      alert_on_failure: formValue.value.alert_on_failure,
      slot_max_tasks: formValue.value.slot_max_tasks,
      slot_max_tasks_enforce: formValue.value.slot_max_tasks_enforce
    }

    if (formValue.value.alert_webhook_url_input.trim()) {
      update.alert_webhook_url = formValue.value.alert_webhook_url_input.trim()
    }

    return update
  }

  function buildSharedPagesSectionUpdate(): RuntimeConfigUpdate {
    return {
      allow_monitor_for_users: formValue.value.allow_monitor_for_users,
      allow_schedule_overview_for_users: formValue.value.allow_schedule_overview_for_users,
      allow_analytics_for_users: formValue.value.allow_analytics_for_users,
      allow_oidc_diagnostics_for_users: formValue.value.allow_oidc_diagnostics_for_users
    }
  }

  function buildGitlabSectionUpdate(): IntegrationConfigUpdate {
    const update: IntegrationConfigUpdate = {
      gitlab_url: formValue.value.gitlab_url.trim()
    }

    if (formValue.value.gitlab_bot_token_input.trim()) {
      update.gitlab_bot_token = formValue.value.gitlab_bot_token_input.trim()
    }

    if (formValue.value.gitlab_admin_token_input.trim()) {
      update.gitlab_admin_token = formValue.value.gitlab_admin_token_input.trim()
    }

    if (formValue.value.gitlab_webhook_secret_input.trim()) {
      update.gitlab_webhook_secret = formValue.value.gitlab_webhook_secret_input.trim()
    }

    return update
  }

  function buildOidcSectionUpdate(): AuthConfigUpdate {
    const update: AuthConfigUpdate = {
      oidc_enabled: formValue.value.oidc_enabled,
      oidc_issuer_url: formValue.value.oidc_issuer_url.trim(),
      oidc_client_id: formValue.value.oidc_client_id.trim(),
      oidc_redirect_uri: formValue.value.oidc_redirect_uri.trim()
    }

    if (formValue.value.oidc_client_secret_input.trim()) {
      update.oidc_client_secret = formValue.value.oidc_client_secret_input.trim()
    }

    return update
  }

  function buildSessionSectionUpdate(): AuthConfigUpdate {
    return {
      session_cookie_name: formValue.value.session_cookie_name.trim(),
      session_ttl_seconds: formValue.value.session_ttl_seconds,
      cookie_secure: formValue.value.cookie_secure,
      cookie_samesite: formValue.value.cookie_samesite,
      auth_admin_usernames: formValue.value.auth_admin_usernames,
      auth_admin_gitlab_groups: formValue.value.auth_admin_gitlab_groups
    }
  }

  function buildSectionPayload(section: ConfigSectionKey): ConfigUpdate {
    switch (section) {
      case 'runtime':
        return { runtime: buildRuntimeSectionUpdate() }
      case 'sharedPages':
        return { runtime: buildSharedPagesSectionUpdate() }
      case 'gitlab':
        return { integration: buildGitlabSectionUpdate() }
      case 'oidc':
        return { auth: buildOidcSectionUpdate() }
      case 'session':
        return { auth: buildSessionSectionUpdate() }
    }
  }

  // ============================================================================
  // Actions
  // ============================================================================

  async function fetchConfig(): Promise<void> {
    loading.value = true
    try {
      syncForm(await getConfig())
    } catch (error) {
      message.error(t('config.failedToFetchConfig'))
    } finally {
      loading.value = false
    }
  }

  function resetSection(section: ConfigSectionKey) {
    copyFields(sectionFieldKeys[section], lastLoadedValue.value, formValue.value)
  }

  async function handleSaveSection(section: ConfigSectionKey): Promise<void> {
    sectionSaving[section] = true
    try {
      syncForm(await updateConfig(buildSectionPayload(section)))
      message.success(t('config.configurationSaved'))
    } catch (error: any) {
      message.error(error?.response?.data?.detail || t('config.failedToSaveConfig'))
    } finally {
      sectionSaving[section] = false
    }
  }

  async function handleClearSecret(
    key: 'oidc_client_secret' | 'anthropic_api_key' | 'alert_webhook_url' | 'gitlab_bot_token' | 'gitlab_admin_token' | 'gitlab_webhook_secret'
  ): Promise<void> {
    const section: ConfigSectionKey =
      key === 'gitlab_bot_token' || key === 'gitlab_admin_token' || key === 'gitlab_webhook_secret'
        ? 'gitlab'
        : key === 'oidc_client_secret'
          ? 'oidc'
          : 'runtime'

    sectionSaving[section] = true
    try {
      if (key === 'gitlab_bot_token') {
        syncForm(await updateConfig({ integration: { clear_gitlab_bot_token: true } }))
        message.success(t('config.gitlabBotTokenCleared'))
      } else if (key === 'gitlab_admin_token') {
        syncForm(await updateConfig({ integration: { clear_gitlab_admin_token: true } }))
        message.success(t('config.gitlabAdminTokenCleared'))
      } else if (key === 'gitlab_webhook_secret') {
        syncForm(await updateConfig({ integration: { clear_gitlab_webhook_secret: true } }))
        message.success(t('config.gitlabWebhookSecretCleared'))
      } else if (key === 'oidc_client_secret') {
        syncForm(await resetConfigKey(key))
        message.success(t('config.oidcSecretCleared'))
      } else if (key === 'anthropic_api_key') {
        syncForm(await updateConfig({ runtime: { clear_anthropic_api_key: true } }))
        message.success(t('config.anthropicApiKeyCleared'))
      } else {
        syncForm(await updateConfig({ runtime: { clear_alert_webhook_url: true } }))
        message.success(t('config.alertWebhookCleared'))
      }
    } catch (error: any) {
      message.error(error?.response?.data?.detail || t('config.failedToClearSecret'))
    } finally {
      sectionSaving[section] = false
    }
  }

  async function handleReload(): Promise<void> {
    await fetchConfig()
  }

  async function handleReset(): Promise<void> {
    pageActionLoading.value = true
    try {
      syncForm(await resetConfig())
      message.success(t('config.resetToDefaults'))
    } catch (error: any) {
      message.error(error?.response?.data?.detail || t('config.failedToResetConfig'))
    } finally {
      pageActionLoading.value = false
    }
  }

  return {
    // State
    formValue,
    lastLoadedValue,
    sectionSaving,
    loading,
    pageActionLoading,

    // Computed
    isDirty,
    anySectionSaving,

    // Section Operations
    isSectionDirty,
    isSectionBusy,
    resetSection,

    // Save Operations
    handleSaveSection,
    handleClearSecret,
    handleReload,
    handleReset,

    // Internal
    syncForm,
    buildRuntimeSectionUpdate,
    buildSharedPagesSectionUpdate,
    buildGitlabSectionUpdate,
    buildOidcSectionUpdate,
    buildSessionSectionUpdate
  }
}

// ============================================================================
// Composable with Provide/Inject
// ============================================================================

/**
 * Provide the config form to child components.
 * Call this once in the parent component (Config.vue).
 */
export function provideConfigForm() {
  const configForm = createConfigForm()
  provide(configFormKey, configForm)
  return configForm
}

/**
 * Inject the shared config form into child components.
 * Use this in panel components to access shared state.
 */
export function useConfigForm(): UseConfigFormReturn {
  const configForm = inject(configFormKey)
  if (!configForm) {
    throw new Error('useConfigForm must be used within a component that has called provideConfigForm()')
  }
  return configForm
}
