<template>
  <div class="login-page">
    <n-card class="login-card" :bordered="false">
      <div class="login-card__header">
        <div class="login-card__brand">
          <div class="login-card__mark">
            <n-icon size="26" :component="RocketOutline" />
          </div>
          <div>
            <h1 class="login-card__title">{{ t('app.brandTitle') }}</h1>
            <p class="login-card__subtitle">{{ t('login.subtitle') }}</p>
          </div>
        </div>
        <LanguageToggle size="small" class="login-card__language-switcher" />
      </div>

      <n-alert v-if="loginReason" type="warning" :show-icon="false" class="login-card__alert">
        {{ loginReason }}
      </n-alert>

      <n-alert v-if="authState.breakGlassEnabled" type="info" :show-icon="false" class="login-card__alert">
        {{ t('login.breakGlassEnabled') }}
      </n-alert>

      <n-tabs v-if="!authState.systemInitialized" type="card" animated class="login-card__tabs">
        <n-tab-pane name="local" :tab="t('login.localAuth')">
          <n-space vertical :size="16">
            <n-input
              v-model:value="localUsername"
              :placeholder="t('login.username')"
              autocomplete="username"
            />
            <n-input
              v-model:value="localPassword"
              type="password"
              show-password-on="click"
              :placeholder="t('login.password')"
              autocomplete="current-password"
              @keyup.enter="handleLocalLogin"
            />
            <n-button
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
            <n-text v-else depth="3" style="text-align: center; display: block;">
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
          class="login-card__gitlab-btn"
          @click="handleLogin"
        >
          {{ t('login.continueWithGitlab') }}
        </n-button>

        <!-- Password Login Toggle -->
        <div class="login-card__password-toggle">
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
          <n-space vertical :size="12">
            <n-input
              v-model:value="localUsername"
              :placeholder="t('login.username')"
              autocomplete="username"
            />
            <n-input
              v-model:value="localPassword"
              type="password"
              show-password-on="click"
              :placeholder="t('login.password')"
              autocomplete="current-password"
              @keyup.enter="handleLocalLogin"
            />
            <n-button
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
          <n-space vertical :size="12">
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
  return typeof reason === 'string' ? reason : ''
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
  flex-direction: column;
  align-items: center;
  justify-content: center;
  width: 100%;
  box-sizing: border-box;
  padding: 24px;
  padding-top: max(24px, env(safe-area-inset-top));
  padding-bottom: max(24px, env(safe-area-inset-bottom));
}

.login-card {
  width: min(460px, 100%);
  margin: 0 auto;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(14px);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
}

.login-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
}

.login-card__brand {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}

.login-card__language-switcher {
  flex-shrink: 0;
  margin-top: 2px;
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
  flex-shrink: 0;
}

.login-card__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.login-card__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.66);
}

.login-card__body {
  margin-top: 20px;
}

.login-card__gitlab-btn {
  margin-top: 16px;
}

.login-card__alert {
  border-radius: 12px;
  font-size: 13px;
  padding: 10px 14px;
}

.login-card__break-glass {
  width: 100%;
}

.login-card__hint {
  display: block;
  line-height: 1.5;
}

.login-card__password-toggle {
  text-align: center;
}

@media (max-width: 767px) {
  .login-page {
    padding-left: 16px;
    padding-right: 16px;
  }

  .login-card__header {
    gap: 12px;
  }

  .login-card__brand {
    gap: 14px;
  }
}

@media (max-width: 480px) {
  .login-card__header {
    flex-direction: column;
    align-items: stretch;
  }

  .login-card__language-switcher {
    align-self: flex-end;
    margin-top: 0;
  }
}
</style>
