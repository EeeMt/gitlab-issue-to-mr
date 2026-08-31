<template>
  <div class="language-toggle" :class="[`language-toggle--${size}`]" :aria-label="t('app.language')" role="group">
    <button
      v-for="option in options"
      :key="option.value"
      type="button"
      class="language-toggle__button"
      :class="{ 'language-toggle__button--active': option.value === currentLocale }"
      :aria-pressed="option.value === currentLocale"
      :title="option.title"
      @click="setAppLocale(option.value)"
    >
      {{ option.label }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { currentLocale, setAppLocale, type AppLocale } from '../i18n'

withDefaults(defineProps<{
  size?: 'small' | 'medium'
}>(), {
  size: 'small'
})

const { t } = useI18n()

const options = computed<Array<{ label: string; title: string; value: AppLocale }>>(() => [
  {
    label: '中',
    title: t('locale.zhCN'),
    value: 'zh-CN'
  },
  {
    label: 'EN',
    title: t('locale.en'),
    value: 'en'
  }
])
</script>

<style scoped>
.language-toggle {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px;
  border-radius: 999px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  background: rgba(255, 255, 255, 0.74);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.45);
  backdrop-filter: blur(10px);
}

.language-toggle__button {
  border: none;
  border-radius: 999px;
  background: transparent;
  color: rgba(15, 23, 42, 0.68);
  font-weight: 700;
  letter-spacing: 0.02em;
  cursor: pointer;
  transition: background-color 0.2s ease, color 0.2s ease, box-shadow 0.2s ease, transform 0.2s ease;
}

.language-toggle__button:hover {
  color: #1e3a8a;
  background: rgba(59, 130, 246, 0.08);
}

.language-toggle__button--active {
  color: #1d4ed8;
  background: #fff;
  box-shadow: 0 2px 10px rgba(15, 23, 42, 0.08);
}

.language-toggle__button:focus-visible {
  outline: 2px solid rgba(37, 99, 235, 0.42);
  outline-offset: 1px;
}

.language-toggle--small .language-toggle__button {
  min-width: 40px;
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
}

.language-toggle--medium .language-toggle__button {
  min-width: 48px;
  height: 32px;
  padding: 0 12px;
  font-size: 13px;
}

@media (max-width: 768px) {
  .language-toggle--small .language-toggle__button {
    min-width: 44px;
    height: 44px;
  }
}
</style>
