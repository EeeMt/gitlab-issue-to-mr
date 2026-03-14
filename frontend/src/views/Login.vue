<template>
  <div class="login-page">
    <n-card class="login-card" :bordered="false">
      <div class="login-card__brand">
        <div class="login-card__mark">
          <n-icon size="26" :component="RocketOutline" />
        </div>
        <div>
          <h1 class="login-card__title">GIMR Admin</h1>
          <p class="login-card__subtitle">Sign in with GitLab to access the dashboard.</p>
        </div>
      </div>

      <n-alert v-if="!authState.oidcEnabled && authState.initialized" type="warning" :show-icon="false">
        OIDC login is not enabled yet. Dashboard auth is currently bypassed.
      </n-alert>

      <n-alert v-if="loginReason" type="warning" :show-icon="false">
        {{ loginReason }}
      </n-alert>

      <n-alert v-if="authState.breakGlassEnabled" type="warning" :show-icon="false">
        Emergency admin access is enabled. Use it only for OIDC recovery or administrator lockout scenarios.
      </n-alert>

      <n-space vertical :size="16" class="login-card__body">
        <n-button
          v-if="authState.oidcEnabled"
          type="primary"
          size="large"
          block
          @click="handleLogin"
        >
          Continue with GitLab
        </n-button>

        <div v-if="authState.breakGlassEnabled" class="login-card__break-glass">
          <n-divider>Emergency access</n-divider>
          <n-space vertical :size="12">
            <n-input
              v-model:value="breakGlassUsername"
              placeholder="Emergency username"
              autocomplete="username"
            />
            <n-input
              v-model:value="breakGlassPassword"
              type="password"
              show-password-on="click"
              placeholder="Emergency password"
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
              Sign in with emergency access
            </n-button>
            <n-text depth="3" class="login-card__hint">
              This path is environment-controlled and should stay disabled during normal operation.
            </n-text>
          </n-space>
        </div>

        <n-text depth="3" class="login-card__hint">
          This dashboard uses GitLab OIDC and stores a server-side session in a secure cookie.
        </n-text>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { computed, ref, watch } from 'vue'
import { NAlert, NButton, NCard, NDivider, NIcon, NInput, NSpace, NText, useMessage } from 'naive-ui'
import { RocketOutline } from '@vicons/ionicons5'
import { useRoute } from 'vue-router'
import { authState, startLogin } from '../auth'
import { breakGlassLogin } from '../api'

const route = useRoute()
const message = useMessage()
const nextTarget = computed(() => {
  const next = route.query.next
  return typeof next === 'string' ? next : '/dashboard'
})
const loginReason = computed(() => {
  const reason = route.query.reason
  return typeof reason === 'string' ? reason : ''
})

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

async function handleBreakGlassLogin() {
  if (!breakGlassUsername.value.trim() || !breakGlassPassword.value) {
    message.error('Enter the emergency username and password')
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
      message.error(typeof detail === 'string' ? detail : 'Emergency login failed')
    } else {
      message.error('Emergency login failed')
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
}

.login-card {
  width: min(460px, 100%);
  margin: 0 auto;
  border-radius: 24px;
  background: rgba(255, 255, 255, 0.86);
  backdrop-filter: blur(14px);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
}

.login-card__brand {
  display: flex;
  align-items: center;
  gap: 16px;
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

.login-card__break-glass {
  width: 100%;
}

.login-card__hint {
  display: block;
  line-height: 1.5;
}

@media (max-width: 767px) {
  .login-page {
    padding-left: 16px;
    padding-right: 16px;
  }
}
</style>
