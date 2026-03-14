<template>
  <div class="login-page">
    <n-card class="login-card" :bordered="false">
      <div class="login-card__brand">
        <div class="login-card__mark">
          <n-icon size="26" :component="RocketOutline" />
        </div>
        <div>
          <h1 class="login-card__title">GitMR Admin</h1>
          <p class="login-card__subtitle">Sign in with GitLab to access the dashboard.</p>
        </div>
      </div>

      <n-alert v-if="!authState.oidcEnabled && authState.initialized" type="warning" :show-icon="false">
        OIDC login is not enabled yet. Dashboard auth is currently bypassed.
      </n-alert>

      <n-space vertical :size="16" class="login-card__body">
        <n-button
          type="primary"
          size="large"
          block
          :disabled="!authState.oidcEnabled"
          @click="handleLogin"
        >
          Continue with GitLab
        </n-button>

        <n-text depth="3" class="login-card__hint">
          This dashboard uses GitLab OIDC and stores a server-side session in a secure cookie.
        </n-text>
      </n-space>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NAlert, NButton, NCard, NIcon, NSpace, NText } from 'naive-ui'
import { RocketOutline } from '@vicons/ionicons5'
import { useRoute } from 'vue-router'
import { authState, startLogin } from '../auth'

const route = useRoute()
const nextTarget = computed(() => {
  const next = route.query.next
  return typeof next === 'string' ? next : '/dashboard'
})

function handleLogin() {
  startLogin(nextTarget.value)
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.login-card {
  width: min(460px, 100%);
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

.login-card__hint {
  display: block;
  line-height: 1.5;
}
</style>
