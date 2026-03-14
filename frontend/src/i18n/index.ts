import { computed, ref } from 'vue'
import { createI18n } from 'vue-i18n'
import { dateEnUS, dateZhCN, enUS, zhCN } from 'naive-ui'
import enMessages from './messages/en'
import zhCNMessages from './messages/zh-CN'

export type AppLocale = 'en' | 'zh-CN'

const LOCALE_STORAGE_KEY = 'gimr-locale'
const FALLBACK_LOCALE: AppLocale = 'en'

function normalizeLocale(value: string | null | undefined): AppLocale | null {
  if (!value) {
    return null
  }

  const normalized = value.toLowerCase()
  if (normalized.startsWith('zh')) {
    return 'zh-CN'
  }
  if (normalized.startsWith('en')) {
    return 'en'
  }
  return null
}

function resolveInitialLocale(): AppLocale {
  if (typeof window !== 'undefined') {
    const storedLocale = normalizeLocale(window.localStorage.getItem(LOCALE_STORAGE_KEY))
    if (storedLocale) {
      return storedLocale
    }

    const browserLocale = normalizeLocale(window.navigator.language)
    if (browserLocale) {
      return browserLocale
    }
  }

  return FALLBACK_LOCALE
}

export const currentLocale = ref<AppLocale>(resolveInitialLocale())

export const i18n = createI18n({
  legacy: false,
  locale: currentLocale.value,
  fallbackLocale: FALLBACK_LOCALE,
  messages: {
    en: enMessages,
    'zh-CN': zhCNMessages
  }
})

export function setAppLocale(locale: AppLocale) {
  currentLocale.value = locale
  i18n.global.locale.value = locale

  if (typeof window !== 'undefined') {
    window.localStorage.setItem(LOCALE_STORAGE_KEY, locale)
  }
}

export const naiveUiLocale = computed(() => (currentLocale.value === 'zh-CN' ? zhCN : enUS))
export const naiveUiDateLocale = computed(() =>
  currentLocale.value === 'zh-CN' ? dateZhCN : dateEnUS
)
