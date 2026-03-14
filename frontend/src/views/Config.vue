<template>
  <div class="config-page">
    <n-space vertical :size="16">
      <div class="config-page__hero">
        <div>
          <h2 class="config-page__title">Configuration</h2>
          <p class="config-page__subtitle">
            Manage scheduler behavior and GitLab OIDC login from one place. Saved values override
            env configuration and survive restarts.
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag size="small" round type="info">DB override</n-tag>
          <n-tag size="small" round>env fallback</n-tag>
          <n-tag size="small" round>default fallback</n-tag>
        </n-space>
      </div>

      <n-alert type="info" :show-icon="false">
        OIDC secrets are stored server-side and never returned to the browser. Leave the client
        secret blank to keep the current stored value.
      </n-alert>

      <n-grid :cols="isMobile ? 1 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="config-summary-card" :bordered="false">
            <div class="config-summary-card__label">{{ item.label }}</div>
            <div class="config-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card class="config-form-card" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">Settings</div>
              <div class="config-card-header__subtitle">Runtime and authentication configuration</div>
            </div>
            <n-space :size="8" align="center">
              <n-tag v-if="isDirty" size="small" type="warning" round>Unsaved changes</n-tag>
              <n-tag v-else size="small" type="success" round>In sync</n-tag>
            </n-space>
          </div>
        </template>

        <n-spin :show="loading">
          <n-form ref="formRef" :model="formValue" :rules="rules" label-placement="top" class="config-form">
            <div class="config-form__section">
              <div class="config-form__section-title">Scheduler</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Max Concurrency" path="max_concurrency">
                    <n-input-number
                      v-model:value="formValue.max_concurrency"
                      :min="1"
                      :max="20"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Maximum number of tasks that can run at the same time.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Scheduler Interval (seconds)" path="scheduler_interval">
                    <n-input-number
                      v-model:value="formValue.scheduler_interval"
                      :min="1"
                      :max="60"
                      class="config-form__input"
                    />
                    <template #feedback>
                      How often the scheduler checks for work.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Task Timeout (seconds)" path="task_timeout">
                    <n-input-number
                      v-model:value="formValue.task_timeout"
                      :min="60"
                      :max="7200"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Maximum execution time before a task is marked failed.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Default Target Branch" path="default_target_branch">
                    <n-input
                      v-model:value="formValue.default_target_branch"
                      placeholder="main"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Default branch used when a task does not specify one.
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="config-form__section">
              <div class="config-form__section-title">GitLab OIDC</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Enable OIDC Login" path="oidc_enabled">
                    <n-switch v-model:value="formValue.oidc_enabled" />
                    <template #feedback>
                      When enabled, dashboard APIs require GitLab sign-in.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Client Secret Status">
                    <n-tag :type="formValue.oidc_client_secret_configured ? 'success' : 'warning'" round>
                      {{ formValue.oidc_client_secret_configured ? 'Configured' : 'Missing' }}
                    </n-tag>
                    <template #feedback>
                      The actual secret is never returned to the browser.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Issuer URL" path="oidc_issuer_url">
                    <n-input
                      v-model:value="formValue.oidc_issuer_url"
                      placeholder="https://gitlab.example.com"
                      class="config-form__input"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Client ID" path="oidc_client_id">
                    <n-input v-model:value="formValue.oidc_client_id" class="config-form__input" />
                  </n-form-item>
                </n-gi>
                <n-gi :span="isMobile ? 1 : 2">
                  <n-form-item label="Client Secret">
                    <n-input
                      v-model:value="formValue.oidc_client_secret_input"
                      type="password"
                      show-password-on="click"
                      :placeholder="
                        formValue.oidc_client_secret_configured
                          ? 'Configured. Enter a new value to rotate it.'
                          : 'Enter client secret'
                      "
                      class="config-form__input"
                    />
                    <template #feedback>
                      Leave blank to keep the stored secret unchanged.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi :span="isMobile ? 1 : 2">
                  <n-form-item label="Redirect URI" path="oidc_redirect_uri">
                    <n-input
                      v-model:value="formValue.oidc_redirect_uri"
                      placeholder="https://your-domain.example.com/api/auth/callback"
                      class="config-form__input"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Session Cookie Name" path="session_cookie_name">
                    <n-input v-model:value="formValue.session_cookie_name" class="config-form__input" />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Session TTL (seconds)" path="session_ttl_seconds">
                    <n-input-number
                      v-model:value="formValue.session_ttl_seconds"
                      :min="300"
                      :max="604800"
                      class="config-form__input"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Cookie Secure" path="cookie_secure">
                    <n-switch v-model:value="formValue.cookie_secure" />
                    <template #feedback>
                      Keep this enabled for HTTPS deployments.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Cookie SameSite" path="cookie_samesite">
                    <n-select
                      v-model:value="formValue.cookie_samesite"
                      :options="sameSiteOptions"
                      class="config-form__input"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Admin Usernames">
                    <n-input
                      v-model:value="formValue.auth_admin_usernames"
                      placeholder="alice,bob"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Comma-separated GitLab usernames bootstrapped as platform admins.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Admin GitLab Groups">
                    <n-input
                      v-model:value="formValue.auth_admin_gitlab_groups"
                      placeholder="platform-team"
                      class="config-form__input"
                    />
                    <template #feedback>
                      Optional group names checked during login.
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>

              <n-alert v-if="oidcTestState" :type="oidcTestState.type" :show-icon="false">
                {{ oidcTestState.message }}
              </n-alert>
            </div>

            <div class="config-form__actions">
              <n-space :size="12" wrap>
                <n-button
                  type="primary"
                  @click="handleSave"
                  :loading="saving"
                  :disabled="loading || saving || !isDirty"
                >
                  Save changes
                </n-button>
                <n-button @click="handleTestOidc" :loading="testing" :disabled="loading || saving || testing">
                  Test OIDC connection
                </n-button>
                <n-button
                  @click="handleClearSecret"
                  :disabled="loading || saving || testing || !formValue.oidc_client_secret_configured"
                >
                  Clear stored secret
                </n-button>
                <n-button @click="handleReload" :disabled="loading || saving || testing">
                  Reload
                </n-button>
                <n-button @click="handleReset" :disabled="loading || saving || testing" secondary>
                  Reset to env/defaults
                </n-button>
              </n-space>
            </div>
          </n-form>
        </n-spin>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
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
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const saving = ref(false)
const testing = ref(false)
const formRef = ref<FormInst | null>(null)
const oidcTestState = ref<OidcTestState | null>(null)

const sameSiteOptions = [
  { label: 'Lax', value: 'lax' },
  { label: 'Strict', value: 'strict' },
  { label: 'None', value: 'none' }
]

const formValue = ref<ConfigForm>({
  max_concurrency: 3,
  task_timeout: 1800,
  scheduler_interval: 5,
  default_target_branch: 'main',
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
  { label: 'Max Concurrency', value: String(formValue.value.max_concurrency) },
  { label: 'Task Timeout', value: `${formValue.value.task_timeout}s` },
  { label: 'OIDC Login', value: formValue.value.oidc_enabled ? 'Enabled' : 'Disabled' },
  {
    label: 'Client Secret',
    value: formValue.value.oidc_client_secret_configured ? 'Configured' : 'Missing'
  }
])

const rules: FormRules = {
  max_concurrency: { required: true, type: 'number', message: 'Enter max concurrency', trigger: 'blur' },
  task_timeout: { required: true, type: 'number', message: 'Enter task timeout', trigger: 'blur' },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: 'Enter scheduler interval',
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: 'Enter default target branch',
    trigger: 'blur'
  },
  oidc_issuer_url: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_issuer_url.trim() || new Error('Issuer URL is required'),
    trigger: ['blur', 'input']
  },
  oidc_client_id: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_client_id.trim() || new Error('Client ID is required'),
    trigger: ['blur', 'input']
  },
  oidc_redirect_uri: {
    validator: () =>
      !formValue.value.oidc_enabled || !!formValue.value.oidc_redirect_uri.trim() || new Error('Redirect URI is required'),
    trigger: ['blur', 'input']
  },
  session_cookie_name: {
    required: true,
    message: 'Enter session cookie name',
    trigger: 'blur'
  },
  session_ttl_seconds: {
    required: true,
    type: 'number',
    message: 'Enter session TTL',
    trigger: 'blur'
  }
}

function syncForm(config: Config) {
  formValue.value = {
    max_concurrency: config.runtime.max_concurrency,
    task_timeout: config.runtime.task_timeout,
    scheduler_interval: config.runtime.scheduler_interval,
    default_target_branch: config.runtime.default_target_branch,
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
      default_target_branch: formValue.value.default_target_branch.trim()
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
    message.error('Failed to fetch config')
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
    message.success('Configuration saved')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to save config')
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
      message: `OIDC discovery succeeded for issuer ${result.issuer || formValue.value.oidc_issuer_url}.`
    }
    message.success('OIDC connection test passed')
  } catch (error: any) {
    const detail = error?.response?.data?.detail || 'OIDC connection test failed'
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
    message.success('Stored OIDC client secret cleared')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to clear stored secret')
  } finally {
    saving.value = false
  }
}

async function handleReset() {
  saving.value = true
  try {
    syncForm(await resetConfig())
    oidcTestState.value = null
    message.success('Configuration reset to env/default values')
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to reset config')
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
  max-width: 1120px;
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

.config-form__actions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
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
