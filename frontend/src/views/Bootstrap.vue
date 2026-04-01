<template>
  <div class="bootstrap-page" data-testid="bootstrap-page">
    <n-card class="bootstrap-card" :bordered="false" data-testid="bootstrap-card">
      <PageHeader data-testid="bootstrap-header" root-class="bootstrap-card__header">
        <template #title>
          <div class="bootstrap-card__brand">
            <div class="bootstrap-card__mark">
              <n-icon :size="isCompact ? 22 : 26" :component="RocketOutline" />
            </div>
            <div>
              <h1 class="bootstrap-card__title">{{ t('app.brandTitle') }}</h1>
              <p class="bootstrap-card__subtitle">{{ t('bootstrap.subtitle') }}</p>
            </div>
          </div>
        </template>
        <template #actions>
          <LanguageToggle size="small" class="bootstrap-card__language-switcher" />
        </template>
      </PageHeader>

      <n-alert type="info" :show-icon="false" class="bootstrap-card__intro">
        {{ t('bootstrap.intro') }}
      </n-alert>

      <n-form
        ref="formRef"
        :model="formData"
        :rules="formRules()"
        label-placement="top"
        class="bootstrap-form"
        data-testid="bootstrap-form"
      >
        <n-form-item :label="t('bootstrap.username')" path="username">
          <n-input
            data-testid="bootstrap-username-input"
            v-model:value="formData.username"
            placeholder="Enter administrator username"
            autocomplete="username"
          />
        </n-form-item>

        <n-form-item :label="t('bootstrap.displayName')" path="displayName">
          <n-input
            data-testid="bootstrap-display-name-input"
            v-model:value="formData.displayName"
            :placeholder="t('bootstrap.displayNamePlaceholder')"
          />
        </n-form-item>

        <n-form-item :label="t('bootstrap.email')" path="email">
          <n-input
            data-testid="bootstrap-email-input"
            v-model:value="formData.email"
            :placeholder="t('bootstrap.emailPlaceholder')"
            autocomplete="email"
          />
        </n-form-item>

        <n-form-item :label="t('bootstrap.password')" path="password">
          <n-input
            data-testid="bootstrap-password-input"
            v-model:value="formData.password"
            type="password"
            show-password-on="click"
            :placeholder="t('bootstrap.passwordPlaceholder')"
            autocomplete="new-password"
          />
        </n-form-item>

        <n-form-item :label="t('bootstrap.confirmPassword')" path="confirmPassword">
          <n-input
            data-testid="bootstrap-confirm-password-input"
            v-model:value="formData.confirmPassword"
            type="password"
            show-password-on="click"
            :placeholder="t('bootstrap.confirmPasswordPlaceholder')"
            autocomplete="new-password"
          />
        </n-form-item>

        <n-space vertical :size="16" class="bootstrap-form__actions">
          <n-button
            data-testid="bootstrap-submit-button"
            type="primary"
            size="large"
            block
            :loading="submitting"
            @click="handleSubmit"
          >
            {{ t('bootstrap.createAdmin') }}
          </n-button>

          <n-text depth="3" class="bootstrap-form__hint">
            {{ t('bootstrap.hint') }}
          </n-text>
        </n-space>
      </n-form>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import axios from 'axios'
import { reactive, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  NAlert,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NIcon,
  NInput,
  NSpace,
  NText,
  FormInst,
  FormRules,
  useMessage
} from 'naive-ui'
import { RocketOutline } from '@vicons/ionicons5'
import LanguageToggle from '../components/LanguageToggle.vue'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'

const message = useMessage()
const { t } = useI18n()
const { isCompact } = useBreakpoints()

const formRef = ref<FormInst | null>(null)
const submitting = ref(false)

const formData = reactive({
  username: '',
  displayName: '',
  email: '',
  password: '',
  confirmPassword: ''
})

// Use function to lazy-evaluate i18n strings (avoids t() calls during module init)
function formRules(): FormRules {
  return {
    username: {
      required: true,
      message: 'Username is required',
      trigger: ['blur', 'input']
    },
    displayName: {
      required: false
    },
    email: {
      required: true,
      pattern: /^[^\s@]+@[^\s@]+\.[^\s@]+$/,
      message: 'Please enter a valid email address',
      trigger: ['blur', 'input']
    },
    password: {
      required: true,
      min: 8,
      message: 'Password must be at least 8 characters',
      trigger: ['blur', 'input']
    },
    confirmPassword: {
      required: true,
      validator: (_rule, value) => {
        if (!value) {
          return new Error('Please confirm your password')
        }
        if (value !== formData.password) {
          return new Error('Passwords do not match')
        }
        return true
      },
      trigger: ['blur', 'input']
    }
  }
}

async function handleSubmit() {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch (errors) {
    // Validation failed
    return
  }

  submitting.value = true
  try {
    const response = await axios.post('/api/auth/local/register', {
      username: formData.username.trim(),
      display_name: formData.displayName.trim() || formData.username.trim(),
      email: formData.email.trim(),
      password: formData.password
    })

    if (response.data.status === 'success') {
      message.success(t('bootstrap.registrationSuccess'))
      // Redirect to dashboard after successful registration
      setTimeout(() => {
        window.location.assign(response.data.next_path || '/dashboard')
      }, 500)
    }
  } catch (error) {
    if (axios.isAxiosError(error)) {
      const detail = error.response?.data?.detail
      if (typeof detail === 'string') {
        message.error(detail)
      } else {
        message.error(t('bootstrap.registrationFailed'))
      }
    } else {
      message.error(t('bootstrap.registrationFailed'))
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.bootstrap-page {
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
  background:
    radial-gradient(circle at top left, rgba(32, 128, 240, 0.12), transparent 28%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.94), rgba(241, 245, 249, 0.98));
}

.bootstrap-card {
  width: min(520px, 100%);
  margin: 0 auto;
  border-radius: var(--app-card-radius, 18px);
  background: rgba(255, 255, 255, 0.88);
  backdrop-filter: blur(14px);
  box-shadow: 0 24px 60px rgba(15, 23, 42, 0.12);
  border: 1px solid rgba(148, 163, 184, 0.14);
}

/* bootstrap-card__header is now PageHeader's root (via root-class). PageHeader provides
   the flex layout; preserve margin-bottom and override the 767 px column-stack so the
   header only stacks at the compact (480 px) breakpoint. */
.bootstrap-card__header {
  margin-bottom: 24px;
}

.bootstrap-card__brand {
  display: flex;
  align-items: center;
  gap: 16px;
  min-width: 0;
  flex: 1;
}

.bootstrap-card__language-switcher {
  flex-shrink: 0;
}

.bootstrap-card__mark {
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

.bootstrap-card__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.bootstrap-card__subtitle {
  margin: 8px 0 0;
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.66));
}

.bootstrap-card__intro {
  margin-bottom: 24px;
}

.bootstrap-form {
  margin-top: 8px;
}

.bootstrap-form__actions {
  margin-top: 24px;
}

.bootstrap-form__hint {
  display: block;
  line-height: 1.5;
  text-align: center;
}

@media (max-width: 767px) {
  .bootstrap-page {
    padding-left: 16px;
    padding-right: 16px;
  }

  /* Keep header horizontal until the compact breakpoint */
  .bootstrap-card :deep(.page-header) {
    flex-direction: row;
    align-items: flex-start;
    gap: 12px;
  }

  .bootstrap-card :deep(.page-header__actions) {
    width: auto;
    justify-content: flex-end;
  }

  .bootstrap-card__brand {
    gap: 14px;
  }
}

@media (max-width: 480px) {
  /* Stack header at compact size */
  .bootstrap-card :deep(.page-header) {
    flex-direction: column;
    align-items: stretch;
  }

  .bootstrap-card :deep(.page-header__actions) {
    justify-content: flex-end;
  }
}
</style>
