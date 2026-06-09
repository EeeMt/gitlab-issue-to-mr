<template>
  <div class="config-layout__main">
    <n-card id="oidc-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.gitlabOidc') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.gitlabOidcSubtitle') }}</div>
          </div>
        </div>
      </template>

      <n-form ref="oidcFormRef" :model="formValue" :rules="oidcRules" label-placement="top" class="config-section-form">
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
        <n-alert v-if="oidcTestState" :type="oidcTestState.type" :show-icon="false" class="config-actions__alert">
          {{ oidcTestState.message }}
        </n-alert>
        <div class="config-card-actions">
          <n-space :size="12" wrap>
            <n-button
              type="primary"
              @click="handleSaveSection('oidc')"
              :loading="sectionSaving.oidc"
              :disabled="isAuthBusy || !isSectionDirty('oidc')"
            >
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              secondary
              @click="resetSection('oidc')"
              :disabled="isAuthBusy || !isSectionDirty('oidc')"
            >
              {{ t('config.revertChanges') }}
            </n-button>
            <n-button
              @click="handleTestOidc"
              :loading="oidcTesting"
              :disabled="isAuthBusy"
            >
              {{ t('config.testOidcConnection') }}
            </n-button>
            <n-button
              @click="handleClearSecret('oidc_client_secret')"
              :disabled="isAuthBusy || !formValue.oidc_client_secret_configured"
            >
              {{ t('config.clearOidcSecret') }}
            </n-button>
          </n-space>
        </div>
      </n-form>
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

      <n-form ref="sessionFormRef" :model="formValue" :rules="sessionRules" label-placement="top" class="config-section-form">
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
              <n-form-item :label="t('config.sessionRetentionDays')" path="session_retention_days">
                <n-input-number
                  v-model:value="formValue.session_retention_days"
                  :min="1"
                  :max="365"
                  class="config-form__input"
                />
                <template #feedback>
                  {{ t('config.sessionRetentionDaysHint') }}
                </template>
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
        <div class="config-card-actions">
          <n-space :size="12" wrap>
            <n-button
              type="primary"
              @click="handleSaveSection('session')"
              :loading="sectionSaving.session"
              :disabled="isAuthBusy || !isSectionDirty('session')"
            >
              {{ t('config.saveChanges') }}
            </n-button>
            <n-button
              secondary
              @click="resetSection('session')"
              :disabled="isAuthBusy || !isSectionDirty('session')"
            >
              {{ t('config.revertChanges') }}
            </n-button>
          </n-space>
        </div>
      </n-form>
    </n-card>

    <OidcDiagnosticsPanel />
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
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
  NSwitch,
  NTag,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useWindowSize } from '@vueuse/core'
import { useMessage } from 'naive-ui'
import { useConfigForm } from './useConfigForm'
import { testOidcConfig } from '../../api'
import OidcDiagnosticsPanel from '../../components/config/OidcDiagnosticsPanel.vue'

const props = defineProps<{
  isMobile?: boolean
}>()

const { t } = useI18n()
const { width } = useWindowSize()
const message = useMessage()
const isMobile = computed(() => props.isMobile ?? width.value < 768)

// Use shared config form
const {
  formValue,
  sectionSaving,
  isSectionDirty,
  handleSaveSection,
  handleClearSecret,
  buildOidcSectionUpdate
} = useConfigForm()

// Auth-specific state
const oidcTesting = ref(false)
const oidcTestState = ref<{ type: 'success' | 'error', message: string } | null>(null)

const isAuthBusy = computed(() =>
  sectionSaving.oidc ||
  sectionSaving.session ||
  oidcTesting.value
)

// Form refs
const oidcFormRef = ref<FormInst | null>(null)
const sessionFormRef = ref<FormInst | null>(null)

// Validation rules
const oidcRules: FormRules = {
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
  }
}

const sessionRules: FormRules = {
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

// SameSite options
const sameSiteOptions = computed(() => [
  { label: 'Lax', value: 'lax' },
  { label: 'Strict', value: 'strict' },
  { label: 'None', value: 'none' }
])

// Reset section helper
function resetSection(section: 'oidc' | 'session') {
  const { resetSection: sharedResetSection } = useConfigForm()
  sharedResetSection(section)
}

// Actions
async function handleTestOidc() {
  oidcTesting.value = true
  try {
    const result = await testOidcConfig(buildOidcSectionUpdate())
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
    oidcTesting.value = false
  }
}
</script>
