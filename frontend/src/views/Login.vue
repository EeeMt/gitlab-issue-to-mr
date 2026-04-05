<template>
  <div class="login-page" data-testid="login-page">
    <n-card class="login-card" :bordered="false" data-testid="login-card">
      <div class="login-card__header" data-testid="login-header">
        <LanguageToggle size="small" class="login-card__lang" />
        <div class="login-card__brand">
          <div class="login-card__mark">
            <n-icon :size="24" :component="RocketOutline" />
          </div>
          <h1 class="login-card__title">{{ t('app.brandTitle') }}</h1>
          <p class="login-card__subtitle">{{ t('login.subtitle') }}</p>
        </div>
      </div>

      <Transition name="login-alert">
        <n-alert v-if="loginReason" type="warning" class="login-card__alert" data-testid="login-reason-alert">
          {{ loginReason }}
        </n-alert>
      </Transition>

      <n-alert v-if="authState.breakGlassEnabled" type="info" :show-icon="false" class="login-card__alert">
        {{ t('login.breakGlassEnabled') }}
      </n-alert>

      <n-tabs
        v-if="!authState.systemInitialized"
        type="card"
        animated
        class="login-card__tabs"
        data-testid="login-tabs"
      >
        <n-tab-pane name="local" :tab="t('login.localAuth')">
          <n-space vertical :size="16" class="login-form">
            <n-input
              data-testid="login-username-input"
              v-model:value="localUsername"
              :placeholder="t('login.username')"
              autocomplete="username"
            />
            <n-input
              data-testid="login-password-input"
              v-model:value="localPassword"
              type="password"
              show-password-on="click"
              :placeholder="t('login.password')"
              autocomplete="current-password"
              @keyup.enter="handleLocalLogin"
            />
            <n-button
              data-testid="login-submit-button"
              type="primary"
              strong
              block
              :loading="localLoading"
              @click="handleLocalLogin"
            >
              {{ t('login.signIn') }}
            </n-button>
          </n-space>
        </n-tab-pane>
        <n-tab-pane name="oidc" :tab="t('login.oidcAuth')">
          <n-space vertical :size="16">
            <n-button
              v-if="authState.oidcEnabled"
              type="primary"
              size="large"
              block
              @click="handleLogin"
            >
              {{ t('login.continueWithGitlab') }}
            </n-button>
            <n-text v-else depth="3" style="display: block;">
              {{ t('login.oidcNotConfigured') }}
            </n-text>
          </n-space>
        </n-tab-pane>
      </n-tabs>

      <n-space v-else vertical :size="16" class="login-card__body">
        <!-- GitLab Login (default) -->
        <n-button
          v-if="!showPasswordLogin && authState.oidcEnabled"
          type="primary"
          size="large"
          block
          @click="handleLogin"
        >
          {{ t('login.continueWithGitlab') }}
        </n-button>

        <!-- Password Login Toggle -->
        <div class="login-card__toggle">
          <n-button
            quaternary
            @click="showPasswordLogin = !showPasswordLogin"
          >
            <template #icon>
              <n-icon :component="showPasswordLogin ? LogoGitlab : KeyOutline" />
            </template>
            {{ showPasswordLogin ? t('login.useGitlabLogin') : t('login.usePasswordLogin') }}
          </n-button>
        </div>

        <!-- Password Login Form -->
        <n-collapse-transition :show="showPasswordLogin">
          <n-space vertical :size="12" data-testid="login-password-form">
            <n-input
              data-testid="login-password-toggle-username-input"
              v-model:value="localUsername"
              :placeholder="t('login.username')"
              autocomplete="username"
            />
            <n-input
              data-testid="login-password-toggle-password-input"
              v-model:value="localPassword"
              type="password"
              show-password-on="click"
              :placeholder="t('login.password')"
              autocomplete="current-password"
              @keyup.enter="handleLocalLogin"
            />
            <n-button
              data-testid="login-password-toggle-submit-button"
              type="primary"
              strong
              block
              :loading="localLoading"
              @click="handleLocalLogin"
            >
              {{ t('login.signIn') }}
            </n-button>
          </n-space>
        </n-collapse-transition>

        <div v-if="authState.breakGlassEnabled" class="login-card__break-glass">
          <n-divider>{{ t('login.emergencyAccess') }}</n-divider>
          <n-space vertical :size="12" class="login-form">
            <n-input
              v-model:value="breakGlassUsername"
              :placeholder="t('login.emergencyUsername')"
              autocomplete="username"
            />
            <n-input
              v-model:value="breakGlassPassword"
              type="password"
              show-password-on="click"
              :placeholder="t('login.emergencyPassword')"
              autocomplete="current-password"
              @keyup.enter="handleBreakGlassLogin"
            />
            <n-button
              type="warning"
              secondary
              strong
              block
              :loading="breakGlassLoading"
              @click="handleBreakGlassLogin"
            >
              {{ t('login.emergencySignIn') }}
            </n-button>
            <n-text depth="3" class="login-card__hint">
              {{ t('login.emergencyHint') }}
            </n-text>
          </n-space>
        </div>

        <n-text depth="3" class="login-card__hint">
          {{ t('login.sessionHint') }}
        </n-text>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NAlert, NButton, NCard, NCollapseTransition, NDivider, NIcon, NInput, NSpace, NTabPane, NTabs, NText, useMessage } from 'naive-ui'
import { LogoGitlab, KeyOutline, RocketOutline } from '@vicons/ionicons5'
import { useRoute } from 'vue-router'
import { authState, startLogin } from '../auth'
import { breakGlassLogin } from '../api'
import LanguageToggle from '../components/LanguageToggle.vue'

const route = useRoute()
const message = useMessage()
const { t } = useI18n()
const nextTarget = computed(() => {
  const next = route.query.next
  return typeof next === 'string' ? next : '/dashboard'
})
const loginReason = computed(() => {
  const reason = route.query.reason
  if (typeof reason !== 'string' || !reason) return ''

  const reasonLower = reason.toLowerCase()
  if (reasonLower.includes('authentication required') || reasonLower.includes('not authenticated') || reasonLower.includes('could not validate')) {
    return t('login.redirectReasons.authRequired')
  }
  if (reasonLower.includes('expired')) {
    return t('login.redirectReasons.sessionExpired')
  }
  if (reasonLower.includes('revoked')) {
    return t('login.redirectReasons.sessionRevoked')
  }
  if (reasonLower.includes('denied') || reasonLower.includes('forbidden') || reasonLower.includes('not authorized')) {
    return t('login.redirectReasons.accessDenied')
  }
  // Unknown reason — show the raw string
  return reason
})

const localUsername = ref('')
const localPassword = ref('')
const localLoading = ref(false)
const showPasswordLogin = ref(false)

const breakGlassUsername = ref(authState.breakGlassUsername || '')
const breakGlassPassword = ref('')
const breakGlassLoading = ref(false)

watch(
  () => authState.breakGlassUsername,
  (value) => {
    breakGlassUsername.value = value || ''
  },
  { immediate: true }
)

function handleLogin() {
  startLogin(nextTarget.value)
}

async function handleLocalLogin() {
  if (!localUsername.value.trim() || !localPassword.value) {
    message.error(t('login.missingCredentials'))
    return
  }

  localLoading.value = true
  try {
    const result = await axios.post('/api/auth/local/login', {
      username: localUsername.value.trim(),
      password: localPassword.value,
      next: nextTarget.value
    })
    window.location.assign(result.data.next_path || nextTarget.value)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : t('login.loginFailed'))
    } else {
      message.error(t('login.loginFailed'))
    }
  } finally {
    localLoading.value = false
    localPassword.value = ''
  }
}

async function handleBreakGlassLogin() {
  if (!breakGlassUsername.value.trim() || !breakGlassPassword.value) {
    message.error(t('login.missingEmergencyCredentials'))
    return
  }

  breakGlassLoading.value = true
  try {
    const result = await breakGlassLogin({
      username: breakGlassUsername.value.trim(),
      password: breakGlassPassword.value,
      next: nextTarget.value
    })
    window.location.assign(result.next_path || nextTarget.value)
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      message.error(typeof detail === 'string' ? detail : t('login.emergencyLoginFailed'))
    } else {
      message.error(t('login.emergencyLoginFailed'))
    }
  } finally {
    breakGlassLoading.value = false
    breakGlassPassword.value = ''
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100dvh;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  box-sizing: border-box;
  padding: 24px;
  padding-top: max(24px, env(safe-area-inset-top));
  padding-bottom: max(24px, env(safe-area-inset-bottom));
  background:
    radial-gradient(circle at top left, rgba(32, 128, 240, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.94), rgba(241, 245, 249, 0.98));
}

.login-card {
  width: min(420px, 100%);
  margin: 0 auto;
  border-radius: var(--app-card-radius, 18px);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

/* ─── Header ─── */
.login-card__header {
  position: relative;
  padding-top: 4px;
}

.login-card__lang {
  position: absolute;
  top: 0;
  right: 0;
}

.login-card__brand {
  display: flex;
  flex-direction: column;
  align-items: center;
  text-align: center;
  gap: 0;
}

.login-card__mark {
  width: 52px;
  height: 52px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 18px;
  background: linear-gradient(135deg, #2080f0, #36ad6a);
  color: #fff;
  box-shadow: 0 12px 24px rgba(32, 128, 240, 0.24);
  margin-bottom: 16px;
}

.login-card__title {
  margin: 0;
  font-size: 26px;
  font-weight: 700;
  line-height: 1.2;
}

.login-card__subtitle {
  margin: 6px 0 0;
  font-size: 14px;
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.55));
}

/* ─── Content ─── */
.login-card__body {
  margin-top: 24px;
}

.login-card__tabs {
  margin-top: 24px;
}

.login-card__alert {
  border-radius: 12px;
  font-size: 13px;
  line-height: 1.6;
  margin-top: 20px;
}

.login-card__alert :deep(.n-alert__icon) {
  top: 50%;
  transform: translateY(-50%);
  margin-top: 0;
  margin-bottom: 0;
}

.login-alert-enter-active {
  transition: all 0.3s ease-out;
}

.login-alert-leave-active {
  transition: all 0.2s ease-in;
}

.login-alert-enter-from {
  opacity: 0;
  transform: translateY(-8px);
}

.login-alert-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}

/* ─── Actions ─── */
.login-card__toggle {
  text-align: center;
}

.login-card__hint {
  display: block;
  text-align: center;
  line-height: 1.5;
  font-size: 13px;
}

.login-card__break-glass {
  width: 100%;
}

/* ─── Responsive ─── */
@media (max-width: 480px) {
  .login-page {
    padding-left: 16px;
    padding-right: 16px;
  }

  .login-card__title {
    font-size: 22px;
  }
}
</style>
