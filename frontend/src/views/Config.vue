<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <div class="config-page__hero">
        <div>
          <h2 class="config-page__title">{{ t('config.title') }}</h2>
          <p class="config-page__subtitle">
            {{ t('config.subtitle') }}
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag v-if="isDirty" size="small" round type="warning">{{ t('config.unsavedChanges') }}</n-tag>
          <n-tag v-else size="small" round type="success">{{ t('config.inSync') }}</n-tag>
          <n-tag size="small" round type="info">{{ t('config.dbOverride') }}</n-tag>
          <n-tag size="small" round>{{ t('config.envFallback') }}</n-tag>
          <n-tag size="small" round>{{ t('config.defaultFallback') }}</n-tag>
        </n-space>
      </div>

      <n-alert type="info" :show-icon="false">
        {{ t('config.secretInfo') }}
      </n-alert>

      <n-grid :cols="isMobile ? 1 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="config-summary-card" :bordered="false">
            <div class="config-summary-card__label">{{ item.label }}</div>
            <div class="config-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-spin :show="loading">
        <n-form ref="formRef" :model="formValue" :rules="rules" label-placement="top" class="config-form">
          <div class="config-layout__main">
            <n-card id="runtime-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                      <div class="config-card-header__title">{{ t('config.runtimeSettings') }}</div>
                      <div class="config-card-header__subtitle">{{ t('config.runtimeSettingsSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="config-form__section">
                  <div class="config-form__section-title">{{ t('config.scheduler') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                      <n-form-item :label="t('config.maxConcurrency')" path="max_concurrency">
                        <n-input-number
                          v-model:value="formValue.max_concurrency"
                          :min="1"
                          :max="20"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.maxConcurrencyHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.schedulerInterval')" path="scheduler_interval">
                        <n-input-number
                          v-model:value="formValue.scheduler_interval"
                          :min="1"
                          :max="60"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.schedulerIntervalHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.taskTimeout')" path="task_timeout">
                        <n-input-number
                          v-model:value="formValue.task_timeout"
                          :min="60"
                          :max="7200"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.taskTimeoutHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                      <n-form-item :label="t('config.defaultTargetBranch')" path="default_target_branch">
                        <n-input
                          v-model:value="formValue.default_target_branch"
                          placeholder="main"
                          class="config-form__input"
                        />
                        <template #feedback>
                          {{ t('config.defaultTargetBranchHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
            </n-card>

            <n-card id="shared-page-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.sharedPageAccess') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.sharedPageAccessSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.pagePermissions') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.allowMonitor')">
                        <n-switch v-model:value="formValue.allow_monitor_for_users" />
                        <template #feedback>
                           {{ t('config.allowMonitorHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.allowScheduleOverview')">
                        <n-switch v-model:value="formValue.allow_schedule_overview_for_users" />
                        <template #feedback>
                           {{ t('config.allowScheduleOverviewHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.allowAnalytics')">
                        <n-switch v-model:value="formValue.allow_analytics_for_users" />
                        <template #feedback>
                           {{ t('config.allowAnalyticsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.allowOidcDiagnostics')">
                        <n-switch v-model:value="formValue.allow_oidc_diagnostics_for_users" />
                        <template #feedback>
                           {{ t('config.allowOidcDiagnosticsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
            </n-card>

            <n-card id="oidc-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.gitlabOidc') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.gitlabOidcSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.providerBasics') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.enableOidcLogin')" path="oidc_enabled">
                        <n-switch v-model:value="formValue.oidc_enabled" />
                        <template #feedback>
                           {{ t('config.enableOidcLoginHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.clientSecretStatus')">
                        <n-tag :type="formValue.oidc_client_secret_configured ? 'success' : 'warning'" round>
                           {{ formValue.oidc_client_secret_configured ? t('config.configured') : t('config.missing') }}
                        </n-tag>
                        <template #feedback>
                           {{ t('config.clientSecretStatusHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.issuerUrl')" path="oidc_issuer_url">
                        <n-input
                          v-model:value="formValue.oidc_issuer_url"
                          placeholder="https://gitlab.example.com"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.clientId')" path="oidc_client_id">
                        <n-input v-model:value="formValue.oidc_client_id" class="config-form__input" />
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                       <n-form-item :label="t('config.clientSecret')">
                        <n-input
                          v-model:value="formValue.oidc_client_secret_input"
                          type="password"
                          show-password-on="click"
                          :placeholder="
                            formValue.oidc_client_secret_configured
                               ? t('config.configuredEnterNew')
                               : t('config.enterClientSecret')
                          "
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.clientSecretHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi :span="isMobile ? 1 : 2">
                       <n-form-item :label="t('config.redirectUri')" path="oidc_redirect_uri">
                        <n-input
                          v-model:value="formValue.oidc_redirect_uri"
                          placeholder="https://your-domain.example.com/api/auth/callback"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
            </n-card>

            <n-card id="session-settings" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.sessionAccess') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.sessionAccessSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.sessionPolicy') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.sessionCookieName')" path="session_cookie_name">
                        <n-input v-model:value="formValue.session_cookie_name" class="config-form__input" />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.sessionTtl')" path="session_ttl_seconds">
                        <n-input-number
                          v-model:value="formValue.session_ttl_seconds"
                          :min="300"
                          :max="604800"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.cookieSecure')" path="cookie_secure">
                        <n-switch v-model:value="formValue.cookie_secure" />
                        <template #feedback>
                           {{ t('config.cookieSecureHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.cookieSameSite')" path="cookie_samesite">
                        <n-select
                          v-model:value="formValue.cookie_samesite"
                          :options="sameSiteOptions"
                          class="config-form__input"
                        />
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>

                <div class="config-form__section">
                   <div class="config-form__section-title">{{ t('config.adminBootstrap') }}</div>
                  <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                    <n-gi>
                       <n-form-item :label="t('config.adminUsernames')">
                        <n-input
                          v-model:value="formValue.auth_admin_usernames"
                           :placeholder="t('config.adminUsernamesPlaceholder')"
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.adminUsernamesHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                    <n-gi>
                       <n-form-item :label="t('config.adminGitlabGroups')">
                        <n-input
                          v-model:value="formValue.auth_admin_gitlab_groups"
                           :placeholder="t('config.adminGitlabGroupsPlaceholder')"
                          class="config-form__input"
                        />
                        <template #feedback>
                           {{ t('config.adminGitlabGroupsHint') }}
                        </template>
                      </n-form-item>
                    </n-gi>
                  </n-grid>
                </div>
            </n-card>

            <n-card id="config-actions" class="config-form-card" :bordered="false">
                <template #header>
                  <div class="config-card-header">
                    <div>
                       <div class="config-card-header__title">{{ t('config.actions') }}</div>
                       <div class="config-card-header__subtitle">{{ t('config.actionsSubtitle') }}</div>
                    </div>
                  </div>
                </template>

                <div class="config-form__section">
                  <n-space :size="12" wrap>
                    <n-button
                      type="primary"
                      @click="handleSave"
                      :loading="saving"
                      :disabled="loading || saving || !isDirty"
                    >
                       {{ t('config.saveChanges') }}
                    </n-button>
                     <n-button @click="handleTestOidc" :loading="testing" :disabled="loading || saving || testing">
                       {{ t('config.testOidcConnection') }}
                     </n-button>
                     <n-button @click="router.push('/oidc-diagnostics')" :disabled="loading || saving || testing">
                       {{ t('config.openOidcDiagnostics') }}
                     </n-button>
                    <n-button
                      @click="handleClearSecret"
                      :disabled="loading || saving || testing || !formValue.oidc_client_secret_configured"
                    >
                       {{ t('config.clearStoredSecret') }}
                     </n-button>
                     <n-button @click="handleReload" :disabled="loading || saving || testing">
                       {{ t('common.reload') }}
                     </n-button>
                     <n-button @click="handleReset" :disabled="loading || saving || testing" secondary>
                       {{ t('config.resetEnvDefaults') }}
                     </n-button>
                  </n-space>
                </div>

                <n-alert v-if="oidcTestState" :type="oidcTestState.type" :show-icon="false" class="config-actions__alert">
                  {{ oidcTestState.message }}
                </n-alert>
            </n-card>
          </div>
        </n-form>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useMessage,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  getConfig,
  resetConfig,
  resetConfigKey,
  testOidcConfig,
  updateConfig,
  type Config,
  type ConfigUpdate
} from '../api'

type ConfigForm = {
  max_concurrency: number
  task_timeout: number
  scheduler_interval: number
  default_target_branch: string
  allow_monitor_for_users: boolean
  allow_schedule_overview_for_users: boolean
  allow_analytics_for_users: boolean
  allow_oidc_diagnostics_for_users: boolean
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
}

type OidcTestState = {
  type: 'success' | 'error'
  message: string
}

const message = useMessage()
const router = useRouter()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const formRef = ref<FormInst | null>(null)
const oidcTestState = ref<OidcTestState | null>(null)

const sameSiteOptions = computed(() => [
  { label: 'Lax', value: 'lax' },
  { label: 'Strict', value: 'strict' },
  { label: 'None', value: 'none' }
])

const formValue = ref<ConfigForm>({
  max_concurrency: 3,
  task_timeout: 1800,
  scheduler_interval: 5,
  default_target_branch: 'main',
  allow_monitor_for_users: false,
  allow_schedule_overview_for_users: false,
  allow_analytics_for_users: false,
  allow_oidc_diagnostics_for_users: false,
  oidc_enabled: false,
  oidc_issuer_url: '',
  oidc_client_id: '',
  oidc_redirect_uri: '',
  session_cookie_name: 'gimr_session',
  session_ttl_seconds: 28800,
  cookie_secure: true,
  cookie_samesite: 'lax',
  auth_admin_usernames: '',
  auth_admin_gitlab_groups: '',
  oidc_client_secret_configured: false,
  oidc_client_secret_input: ''
})

const lastLoadedValue = ref<ConfigForm>({ ...formValue.value })

function comparableValue(value: ConfigForm) {
  const { oidc_client_secret_input, ...rest } = value
  return rest
}

const isDirty = computed(() => {
  if (formValue.value.oidc_client_secret_input.trim()) {
    return true
  }

  return (
    JSON.stringify(comparableValue(formValue.value)) !==
    JSON.stringify(comparableValue(lastLoadedValue.value))
  )
})

const summaryItems = computed(() => [
  { label: t('config.maxConcurrency'), value: String(formValue.value.max_concurrency) },
  { label: t('config.taskTimeout'), value: `${formValue.value.task_timeout}s` },
  {
    label: t('config.sharedPages'),
    value:
      [
        formValue.value.allow_monitor_for_users ? t('nav.monitor') : null,
        formValue.value.allow_schedule_overview_for_users ? t('nav.scheduleOverview') : null,
        formValue.value.allow_analytics_for_users ? t('nav.analytics') : null,
        formValue.value.allow_oidc_diagnostics_for_users ? t('nav.oidcDiagnostics') : null
      ]
        .filter(Boolean)
        .join(', ') || t('config.adminOnly')
  },
  { label: t('config.oidcLogin'), value: formValue.value.oidc_enabled ? t('common.enabled') : t('common.disabled') },
  {
    label: t('config.clientSecret'),
    value: formValue.value.oidc_client_secret_configured ? t('config.configured') : t('config.missing')
  }
])

const rules: FormRules = {
  max_concurrency: { required: true, type: 'number', message: t('config.enterMaxConcurrency'), trigger: 'blur' },
  task_timeout: { required: true, type: 'number', message: t('config.enterTaskTimeout'), trigger: 'blur' },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: t('config.enterSchedulerInterval'),
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: t('config.enterDefaultTargetBranch'),
    trigger: 'blur'
  },
  oidc_issuer_url: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_issuer_url.trim() || new Error(t('config.issuerRequired')),
    trigger: ['blur', 'input']
  },
  oidc_client_id: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_client_id.trim() || new Error(t('config.clientIdRequired')),
    trigger: ['blur', 'input']
  },
  oidc_redirect_uri: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_redirect_uri.trim() || new Error(t('config.redirectUriRequired')),
    trigger: ['blur', 'input']
  },
  session_cookie_name: {
    required: true,
    message: t('config.enterSessionCookieName'),
    trigger: 'blur'
  },
  session_ttl_seconds: {
    required: true,
    type: 'number',
    message: t('config.enterSessionTtl'),
    trigger: 'blur'
  }
}

function syncForm(config: Config) {
  formValue.value = {
    max_concurrency: config.runtime.max_concurrency,
    task_timeout: config.runtime.task_timeout,
    scheduler_interval: config.runtime.scheduler_interval,
    default_target_branch: config.runtime.default_target_branch,
    allow_monitor_for_users: config.runtime.allow_monitor_for_users,
    allow_schedule_overview_for_users: config.runtime.allow_schedule_overview_for_users,
    allow_analytics_for_users: config.runtime.allow_analytics_for_users,
    allow_oidc_diagnostics_for_users: config.runtime.allow_oidc_diagnostics_for_users,
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
    oidc_client_secret_input: ''
  }
  lastLoadedValue.value = { ...formValue.value }
}

function buildPayload(): ConfigUpdate {
  const payload: ConfigUpdate = {
    runtime: {
      max_concurrency: formValue.value.max_concurrency,
      task_timeout: formValue.value.task_timeout,
      scheduler_interval: formValue.value.scheduler_interval,
      default_target_branch: formValue.value.default_target_branch.trim(),
      allow_monitor_for_users: formValue.value.allow_monitor_for_users,
      allow_schedule_overview_for_users: formValue.value.allow_schedule_overview_for_users,
      allow_analytics_for_users: formValue.value.allow_analytics_for_users,
      allow_oidc_diagnostics_for_users: formValue.value.allow_oidc_diagnostics_for_users
    },
    auth: {
      oidc_enabled: formValue.value.oidc_enabled,
      oidc_issuer_url: formValue.value.oidc_issuer_url.trim(),
      oidc_client_id: formValue.value.oidc_client_id.trim(),
      oidc_redirect_uri: formValue.value.oidc_redirect_uri.trim(),
      session_cookie_name: formValue.value.session_cookie_name.trim(),
      session_ttl_seconds: formValue.value.session_ttl_seconds,
      cookie_secure: formValue.value.cookie_secure,
      cookie_samesite: formValue.value.cookie_samesite,
      auth_admin_usernames: formValue.value.auth_admin_usernames,
      auth_admin_gitlab_groups: formValue.value.auth_admin_gitlab_groups
    }
  }

  if (formValue.value.oidc_client_secret_input.trim()) {
    payload.auth!.oidc_client_secret = formValue.value.oidc_client_secret_input.trim()
  }

  return payload
}

async function fetchConfig() {
  loading.value = true
  oidcTestState.value = null
  try {
    syncForm(await getConfig())
  } catch (error) {
    message.error(t('config.failedToFetchConfig'))
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  const valid = await formRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) {
    return
  }

  saving.value = true
  try {
    syncForm(await updateConfig(buildPayload()))
    oidcTestState.value = null
    message.success(t('config.configurationSaved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToSaveConfig'))
  } finally {
    saving.value = false
  }
}

async function handleTestOidc() {
  testing.value = true
  try {
    const result = await testOidcConfig(buildPayload().auth || {})
      oidcTestState.value = {
      type: 'success',
      message: t('config.oidcDiscoverySucceeded', {
        issuer: result.issuer || formValue.value.oidc_issuer_url,
        scopes: result.required_scopes.join(', ')
      })
    }
    message.success(t('config.oidcConnectionPassed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.oidcConnectionFailed')
    oidcTestState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    testing.value = false
  }
}

async function handleClearSecret() {
  saving.value = true
  try {
    syncForm(await resetConfigKey('oidc_client_secret'))
    message.success(t('config.storedSecretCleared'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToClearSecret'))
  } finally {
    saving.value = false
  }
}

async function handleReset() {
  saving.value = true
  try {
    syncForm(await resetConfig())
    oidcTestState.value = null
    message.success(t('config.resetToDefaults'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToResetConfig'))
  } finally {
    saving.value = false
  }
}

function handleReload() {
  fetchConfig()
}

onMounted(() => {
  fetchConfig()
})
</script>

<style scoped>
.config-page {
  max-width: 1240px;
  padding: 8px 0;
}

.config-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.config-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.config-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.config-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.config-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.config-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.config-form-card {
  border-radius: 18px;
}

.config-layout__main {
  display: grid;
  gap: 16px;
}

.config-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.config-card-header__title {
  font-size: 18px;
  font-weight: 600;
}

.config-card-header__subtitle {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
  margin-top: 4px;
}

.config-form {
  margin-top: 8px;
}

.config-form__section + .config-form__section {
  margin-top: 20px;
}

.config-form__section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(15, 23, 42, 0.62);
  text-transform: uppercase;
}

.config-form__input {
  width: 100%;
}

.config-actions__alert {
  margin-top: 16px;
}

@media (max-width: 767px) {
  .config-page__hero,
  .config-card-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .config-page__title {
    font-size: 24px;
  }

  .config-page__subtitle {
    max-width: none;
  }
}
</style>
