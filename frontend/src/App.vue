<template>
  <n-config-provider :locale="naiveUiLocale" :date-locale="naiveUiDateLocale" :theme-overrides="popconfirmThemeOverrides">
    <n-message-provider>
    <n-dialog-provider>
      <div v-if="!authState.initialized" class="app-loading">
        <n-spin size="large" />
      </div>

      <router-view v-else-if="!showShell" />

      <n-layout v-else has-sider position="absolute" style="top: 0; bottom: 0" :native-scrollbar="false" class="app-shell">
        <n-layout-sider
          v-if="!isMobile"
          bordered
          collapse-mode="width"
          :collapsed-width="72"
          :width="272"
          :collapsed="collapsed"
          show-trigger
          :native-scrollbar="false"
          :content-style="collapsed ? 'padding: 18px 0;' : 'padding: 18px 14px;'"
          class="app-shell__sider"
          @collapse="collapsed = true"
          @expand="collapsed = false"
        >
          <div class="logo" :class="{ 'logo--collapsed': collapsed }">
            <div class="logo__mark">
              <n-icon size="22" :component="RocketOutline" />
            </div>
            <div v-if="!collapsed" class="logo__copy">
              <n-text strong class="logo__title">{{ t('app.brandTitle') }}</n-text>
              <n-text depth="3" class="logo__subtitle">{{ t('app.brandSubtitle') }}</n-text>
            </div>
          </div>

          <n-menu
            class="nav-menu"
            :collapsed="collapsed"
            :collapsed-width="72"
            :options="menuOptions"
            :value="activeKey"
            @update:value="handleMenuUpdate"
          />
        </n-layout-sider>

        <n-drawer v-if="isMobile" v-model:show="showDrawer" :width="288" placement="left">
          <n-drawer-content :native-scrollbar="false" body-content-style="padding: 18px 14px;" closable>
            <template #header>
              <div class="mobile-drawer-header">
                <div class="mobile-drawer-header__brand">
                   <div class="logo__mark logo__mark--mobile">
                     <n-icon size="20" :component="RocketOutline" />
                   </div>
                   <div class="logo__copy">
                     <n-text strong class="logo__title">{{ t('app.brandTitle') }}</n-text>
                     <n-text depth="3" class="logo__subtitle">{{ t('app.navigation') }}</n-text>
                   </div>
                 </div>
               </div>
            </template>

            <n-menu
              class="nav-menu"
              :options="menuOptions"
              :value="activeKey"
              @update:value="(key: string) => { handleMenuUpdate(key); showDrawer = false }"
            />
          </n-drawer-content>
        </n-drawer>

        <n-layout :native-scrollbar="false" class="app-shell__main">
          <div v-if="showUserToolbar && !isMobile" class="app-shell__topbar-wrapper">
            <div
              v-if="announcement?.enabled && announcement?.text"
              class="app-shell__announcement-banner"
            >
              <div
                class="app-shell__topbar-announcement-pill"
                :class="`app-shell__topbar-announcement-pill--${announcement.level}`"
              >
                <n-icon :component="announcementIcon" size="13" class="app-shell__topbar-announcement-icon" />
                <div
                  ref="announcementMarqueeRef"
                  class="app-shell__topbar-announcement-marquee"
                  :class="{ 'app-shell__topbar-announcement-marquee--scrolling': announcementOverflows }"
                >
                  <span ref="announcementTextRef" class="app-shell__topbar-announcement-text">{{ announcement.text }}</span>
                </div>
              </div>
            </div>
            <div class="app-shell__topbar">
              <div class="app-shell__topbar-user">
              <n-avatar round size="small" :src="authState.user?.avatar_url || undefined">
                {{ userInitial }}
              </n-avatar>
              <div class="nav-user-panel__copy">
                <n-text strong>{{ userDisplayName }}</n-text>
                <n-text depth="3" class="nav-user-panel__role">
                  {{ authState.user?.platform_role === 'platform_admin' ? t('shell.admin') : t('shell.signedInWithGitlab') }}
                </n-text>
              </div>
            </div>
            <div class="app-shell__topbar-actions">
              <n-tooltip v-if="usageSummary" trigger="hover" :style="usageTooltipStyle">
                <template #trigger>
                  <n-button
                    tertiary
                    circle
                    data-testid="usage-indicator-desktop"
                    class="usage-indicator"
                    :class="`usage-indicator--${usageSummary.severity}`"
                    :title="t(usageSeverityLabelKey)"
                  >
                    <template #icon>
                      <n-icon :component="SpeedometerOutline" />
                    </template>
                  </n-button>
                </template>
                <div class="usage-indicator__tooltip">
                  <div class="usage-indicator__tooltip-title">{{ t(usageSeverityLabelKey) }}</div>
                  <div v-for="item in usageTooltipItems" :key="item.labelKey" class="usage-indicator__tooltip-row">
                    <div class="usage-indicator__tooltip-row-top">
                      <span class="usage-indicator__tooltip-label">{{ t(item.labelKey) }}</span>
                      <span class="usage-indicator__tooltip-value">
                        {{ formatLargeNumber(item.used) }} / {{ formatUsageLimitDisplay(item.limitNumeric, item.limit) }}
                        &nbsp;({{ formatUsagePercent(item.used, item.limitNumeric) }})
                      </span>
                    </div>
                    <div class="usage-indicator__progress">
                      <div
                        class="usage-indicator__progress-fill"
                        :class="`usage-indicator__progress-fill--${usageSummary.severity}`"
                        :style="{ width: formatUsagePercent(item.used, item.limitNumeric) }"
                      />
                    </div>
                  </div>
                  <div class="usage-indicator__tooltip-row usage-indicator__tooltip-row--reset">
                    <span>{{ t('shell.dailyReset') }}</span>
                    <span>{{ formatUsageResetAt(usageSummary.reset_at.daily) }}</span>
                  </div>
                  <div class="usage-indicator__tooltip-row usage-indicator__tooltip-row--reset">
                    <span>{{ t('shell.weeklyReset') }}</span>
                    <span>{{ formatUsageResetAt(usageSummary.reset_at.weekly) }}</span>
                  </div>
                </div>
              </n-tooltip>
              <LanguageToggle size="small" class="app-shell__language-toggle" />
              <n-tooltip trigger="hover" :style="onboardingTooltipStyle">
                <template #trigger>
                  <n-button
                    tertiary
                    circle
                    class="app-shell__onboarding-button app-shell__onboarding-button--icon-only"
                    data-testid="reopen-onboarding-desktop"
                    :title="t('shell.reopenOnboarding')"
                    @click="openOnboarding"
                  >
                    <template #icon>
                      <n-icon :component="InformationCircleOutline" />
                    </template>
                  </n-button>
                </template>
                {{ t('shell.productTour') }}
              </n-tooltip>
              <n-button tertiary class="app-shell__logout-button" @click="handleLogout">
                <template #icon>
                  <n-icon :component="LogOutOutline" />
                </template>
                {{ t('shell.logout') }}
              </n-button>
            </div>
          </div>
          </div>

          <div v-if="isMobile" class="mobile-header">
            <div class="mobile-header__left">
              <n-button quaternary circle class="mobile-header__menu-button" @click="showDrawer = true">
                <template #icon>
                  <n-icon :component="MenuOutline" />
                </template>
              </n-button>
              <div class="mobile-header__copy">
                <n-text depth="3" class="mobile-header__eyebrow">{{ t('app.brandTitle') }}</n-text>
                <n-text strong class="mobile-header__title">{{ currentPageLabel }}</n-text>
              </div>
            </div>
            <div class="mobile-header__actions">
              <div v-if="showUserToolbar" class="mobile-header__user-chip">
                <n-avatar round size="small" :src="authState.user?.avatar_url || undefined">
                  {{ userInitial }}
                </n-avatar>
                <span class="mobile-header__user-name">{{ userDisplayName }}</span>
              </div>
              <LanguageToggle size="small" class="mobile-header__language-toggle" />
              <n-button
                v-if="showUserToolbar"
                quaternary
                circle
                data-testid="reopen-onboarding-mobile"
                class="mobile-header__onboarding-button"
                :title="t('shell.reopenOnboarding')"
                @click="openOnboarding"
              >
                <template #icon>
                  <n-icon :component="InformationCircleOutline" />
                </template>
              </n-button>
              <n-button
                v-if="showUserToolbar"
                quaternary
                circle
                class="mobile-header__logout-button"
                :title="t('shell.logout')"
                @click="handleLogout"
              >
                <template #icon>
                  <n-icon :component="LogOutOutline" />
                </template>
              </n-button>
            </div>
          </div>

          <n-layout content-style="padding: 20px;" :native-scrollbar="false" class="app-shell__content">
            <div class="app-shell__content-inner">
              <router-view />
              <footer class="app-footer">
                <span class="app-footer__text">Powered by</span>
                <a
                  href="https://github.com/EeeMt/codify"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="app-footer__link"
                >
                  <n-icon size="13" :component="LogoGithub" class="app-footer__icon" />
                  Codify
                </a>
              </footer>
            </div>
          </n-layout>

          <OnboardingModal
            :show="showOnboarding"
            @close="handleOnboardingClose"
            @complete="handleOnboardingComplete"
            @view-dashboard="navigateToDashboard"
            @create-issue="navigateToCreateIssue"
          />
        </n-layout>
      </n-layout>
    </n-dialog-provider>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, h, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import {
  NAvatar,
  NButton,
  NConfigProvider,
  NDialogProvider,
  NDrawer,
  NDrawerContent,
  NIcon,
  NLayout,
  NLayoutSider,
  NMenu,
  NMessageProvider,
  NSpin,
  NTooltip,
  NText
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  BarChartOutline,
  DocumentTextOutline,
  FingerPrintOutline,
  GridOutline,
  ListOutline,
  LogOutOutline,
  MenuOutline,
  InformationCircleOutline,
  LogoGithub,
  CalendarOutline,
  PeopleOutline,
  RocketOutline,
  SettingsOutline,
  SpeedometerOutline,
  MegaphoneOutline
} from '@vicons/ionicons5'
import { authState, canAccessSharedPage, initializeAuth, isAdmin, logoutAndClearAuth } from './auth'
import { getMyUsageSummary, getAnnouncement, type CurrentUserUsageSummary, type AnnouncementInfo } from './api'
import LanguageToggle from './components/LanguageToggle.vue'
import OnboardingModal from './components/OnboardingModal.vue'
import { useBreakpoints } from './composables/useBreakpoints'
import { getOnboardingDismissed, setOnboardingDismissed } from './composables/useOnboarding'
import { formatLargeNumber, formatUsageResetAt } from './utils/usageLimits'
import {
  naiveUiDateLocale,
  naiveUiLocale,
} from './i18n'

const router = useRouter()
const route = useRoute()
const { t } = useI18n()
const collapsed = ref(false)
const showDrawer = ref(false)

const { isMobile } = useBreakpoints()

const popconfirmThemeOverrides = {
  Popover: {
    borderRadius: '18px',
    boxShadow: '0 8px 32px rgba(15, 23, 42, 0.25)',
  }
}

const activeKey = computed(() => route.name as string)
const isLoginRoute = computed(() => route.name === 'Login')
const isBootstrapRoute = computed(() => route.name === 'Bootstrap')
const showShell = computed(() => !isLoginRoute.value && !isBootstrapRoute.value)

const menuLabels: Record<string, string> = {
  Dashboard: 'nav.dashboard',
  TaskList: 'nav.tasks',
  Issues: 'nav.issues',
  CreateIssue: 'nav.createIssue',
  Sessions: 'nav.sessions',
  Monitor: 'nav.monitor',
  ScheduleOverview: 'nav.scheduleOverview',
  Analytics: 'nav.analytics',
  Config: 'nav.config',
  AccessManagement: 'nav.accessManagement',
  UsageManagement: 'nav.usageManagement'
}

const onboardingTooltipStyle = {
  fontSize: '11px',
  padding: '4px 8px',
  borderRadius: '6px',
}

const usageTooltipStyle = {
  borderRadius: '12px',
  padding: '12px 16px',
  fontSize: '12px',
}

const currentPageLabel = computed(() => t(menuLabels[activeKey.value] || 'app.navigation'))
const showUserToolbar = computed(() => authState.authenticated)
const onboardingDismissed = ref(getOnboardingDismissed())
const manualOnboardingOpen = ref(false)
const usageSummary = ref<CurrentUserUsageSummary | null>(null)
const usageRefreshTimer = ref<ReturnType<typeof setInterval> | null>(null)
const usageSummaryRequestToken = ref(0)
const announcement = ref<AnnouncementInfo | null>(null)
const announcementRefreshTimer = ref<ReturnType<typeof setInterval> | null>(null)
const announcementMarqueeRef = ref<HTMLElement | null>(null)
const announcementTextRef = ref<HTMLElement | null>(null)
const announcementOverflows = ref(false)

function updateAnnouncementOverflow() {
  const marquee = announcementMarqueeRef.value
  const text = announcementTextRef.value
  if (!marquee || !text) {
    announcementOverflows.value = false
    return
  }
  const overflows = text.scrollWidth > marquee.clientWidth
  announcementOverflows.value = overflows
  if (overflows) {
    const offset = text.scrollWidth - marquee.clientWidth
    marquee.style.setProperty('--scroll-offset', `-${offset}px`)
  }
}

const announcementIcon = computed(() => MegaphoneOutline)
const showOnboarding = computed(
  () => authState.initialized && authState.authenticated && showShell.value && (!onboardingDismissed.value || manualOnboardingOpen.value)
)
const userDisplayName = computed(
  () => authState.user?.display_name || authState.user?.username || t('shell.gitlabUser')
)
const userInitial = computed(() => userDisplayName.value.slice(0, 1).toUpperCase())
const renderIcon = (icon: any) => () => h(NIcon, null, { default: () => h(icon) })
const shouldGroupMenu = computed(() => !collapsed.value || isMobile.value)
const usageSeverityLabelKey = computed(() => {
  switch (usageSummary.value?.severity) {
    case 'over_limit':
      return 'shell.usageOverLimit'
    case 'near_limit':
      return 'shell.usageNearLimit'
    default:
      return 'shell.usageNormal'
  }
})
const usageTooltipItems = computed(() => {
  if (!usageSummary.value) {
    return []
  }

  return [
    {
      labelKey: 'shell.dailyTokens',
      used: usageSummary.value.usage.daily_tokens,
      limit: formatUsageLimit(usageSummary.value.limits.daily_tokens),
      limitNumeric: usageSummary.value.limits.daily_tokens.value,
    },
    {
      labelKey: 'shell.weeklyTokens',
      used: usageSummary.value.usage.weekly_tokens,
      limit: formatUsageLimit(usageSummary.value.limits.weekly_tokens),
      limitNumeric: usageSummary.value.limits.weekly_tokens.value,
    },
    {
      labelKey: 'shell.dailyTasks',
      used: usageSummary.value.usage.daily_tasks,
      limit: formatUsageLimit(usageSummary.value.limits.daily_tasks),
      limitNumeric: usageSummary.value.limits.daily_tasks.value,
    },
    {
      labelKey: 'shell.weeklyTasks',
      used: usageSummary.value.usage.weekly_tasks,
      limit: formatUsageLimit(usageSummary.value.limits.weekly_tasks),
      limitNumeric: usageSummary.value.limits.weekly_tasks.value,
    },
  ]
})

function formatUsageLimit(limit: CurrentUserUsageSummary['limits']['daily_tokens']) {
  return limit.mode === 'unlimited' || limit.value === null ? t('shell.usageUnlimited') : String(limit.value)
}

function formatUsageLimitDisplay(limitNumeric: number | null, fallback: string): string {
  if (limitNumeric === null) return fallback
  return formatLargeNumber(limitNumeric)
}

function formatUsagePercent(used: number, limitNumeric: number | null): string {
  if (limitNumeric === null || limitNumeric <= 0) return '0%'
  const pct = Math.min((used / limitNumeric) * 100, 100)
  return `${Math.round(pct)}%`
}

function buildMenuItem(labelKey: string, key: string, icon: any): MenuOption {
  return {
    label: t(labelKey),
    key,
    icon: renderIcon(icon)
  }
}

function buildMenuSection(labelKey: string, children: MenuOption[]): MenuOption[] {
  if (!children.length) {
    return []
  }

  if (!shouldGroupMenu.value) {
    return children
  }

  return [
    {
      type: 'group',
      key: `group-${labelKey.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`,
      label: t(labelKey),
      children
    }
  ]
}

const menuOptions = computed<MenuOption[]>(() => {
  const workspaceItems: MenuOption[] = [
    buildMenuItem('nav.dashboard', 'Dashboard', GridOutline),
    buildMenuItem('nav.issues', 'Issues', DocumentTextOutline),
    buildMenuItem('nav.tasks', 'TaskList', ListOutline),
  ]

  if (authState.authenticated) {
    workspaceItems.push(buildMenuItem('nav.sessions', 'Sessions', FingerPrintOutline))
  }

  const insightsItems: MenuOption[] = []

  if (canAccessSharedPage('analytics')) {
    insightsItems.push(buildMenuItem('nav.analytics', 'Analytics', BarChartOutline))
  }

  if (canAccessSharedPage('schedule_overview')) {
    insightsItems.push(buildMenuItem('nav.scheduleOverview', 'ScheduleOverview', CalendarOutline))
  }

  if (canAccessSharedPage('monitor')) {
    insightsItems.push(buildMenuItem('nav.monitor', 'Monitor', SpeedometerOutline))
  }

  const adminItems: MenuOption[] = []

  if (!authState.oidcEnabled || isAdmin.value) {
    adminItems.push(buildMenuItem('nav.accessManagement', 'AccessManagement', PeopleOutline))
    adminItems.push(buildMenuItem('nav.usageManagement', 'UsageManagement', RocketOutline))
    adminItems.push(buildMenuItem('nav.config', 'Config', SettingsOutline))
  }

  return [
    ...buildMenuSection('nav.workspace', workspaceItems),
    ...buildMenuSection('nav.insights', insightsItems),
    ...buildMenuSection('nav.administration', adminItems)
  ]
})

function handleMenuUpdate(key: string) {
  router.push({ name: key })
}

function openOnboarding() {
  manualOnboardingOpen.value = true
}

function dismissOnboarding() {
  if (!onboardingDismissed.value) {
    onboardingDismissed.value = true
    setOnboardingDismissed(true)
  }
}

function handleOnboardingClose() {
  dismissOnboarding()
  manualOnboardingOpen.value = false
}

function handleOnboardingComplete() {
  dismissOnboarding()
  manualOnboardingOpen.value = false
}

async function navigateToDashboard() {
  handleOnboardingComplete()
  await router.push({ name: 'Dashboard' })
}

async function navigateToCreateIssue() {
  handleOnboardingComplete()
  await router.push({ name: 'CreateIssue' })
}

async function handleLogout() {
  await logoutAndClearAuth()
}

async function loadUsageSummary() {
  if (!showShell.value || !authState.authenticated || !authState.user?.id) {
    usageSummaryRequestToken.value += 1
    usageSummary.value = null
    return
  }

  const requestToken = ++usageSummaryRequestToken.value
  const requestedUserId = authState.user.id

  try {
    const summary = await getMyUsageSummary()
    if (
      requestToken !== usageSummaryRequestToken.value ||
      !showShell.value ||
      !authState.authenticated ||
      authState.user?.id !== requestedUserId
    ) {
      return
    }
    usageSummary.value = summary
  } catch {
    if (
      requestToken !== usageSummaryRequestToken.value ||
      !showShell.value ||
      !authState.authenticated ||
      authState.user?.id !== requestedUserId
    ) {
      return
    }
    usageSummary.value = null
  }
}

function stopUsageRefresh() {
  if (usageRefreshTimer.value !== null) {
    clearInterval(usageRefreshTimer.value)
    usageRefreshTimer.value = null
  }
}

function startUsageRefresh() {
  stopUsageRefresh()
  if (!showShell.value || !authState.authenticated || !authState.user?.id) {
    return
  }
  usageRefreshTimer.value = setInterval(() => {
    void loadUsageSummary()
  }, 60_000)
}

async function loadAnnouncement() {
  if (!showShell.value || !authState.authenticated) {
    announcement.value = null
    return
  }
  try {
    announcement.value = await getAnnouncement()
    await nextTick()
    updateAnnouncementOverflow()
  } catch {
    announcement.value = null
  }
}

function stopAnnouncementRefresh() {
  if (announcementRefreshTimer.value !== null) {
    clearInterval(announcementRefreshTimer.value)
    announcementRefreshTimer.value = null
  }
}

function startAnnouncementRefresh() {
  stopAnnouncementRefresh()
  if (!showShell.value || !authState.authenticated) {
    return
  }
  announcementRefreshTimer.value = setInterval(() => {
    void loadAnnouncement()
  }, 300_000) // 5 minutes
}

watch(
  () => [showShell.value, authState.authenticated, authState.user?.id],
  () => {
    void loadUsageSummary()
    startUsageRefresh()
    void loadAnnouncement()
    startAnnouncementRefresh()
  },
  { immediate: true }
)

watch(announcementMarqueeRef, (el) => {
  announcementResizeObserver?.disconnect()
  if (el && announcementResizeObserver) {
    announcementResizeObserver.observe(el)
    updateAnnouncementOverflow()
  }
})

let scrollTimer: ReturnType<typeof setTimeout>

function onDocumentScroll() {
  document.documentElement.classList.add('is-scrolling')
  clearTimeout(scrollTimer)
  scrollTimer = setTimeout(() => {
    document.documentElement.classList.remove('is-scrolling')
  }, 600)
}

let announcementResizeObserver: ResizeObserver | null = null

onMounted(() => {
  initializeAuth()
  document.addEventListener('scroll', onDocumentScroll, { capture: true, passive: true })
  announcementResizeObserver = new ResizeObserver(() => {
    updateAnnouncementOverflow()
  })
})

onBeforeUnmount(() => {
  stopUsageRefresh()
  stopAnnouncementRefresh()
  usageSummaryRequestToken.value += 1
  document.removeEventListener('scroll', onDocumentScroll, { capture: true })
  clearTimeout(scrollTimer)
  announcementResizeObserver?.disconnect()
  announcementResizeObserver = null
})
</script>

<style>
:root {
  --app-page-max-width: 1240px;
  --app-page-max-width-wide: 1400px;
  --app-page-gap: 16px;
  --app-page-gap-large: 20px;
  --app-card-radius: 18px;
  --app-card-radius-small: 12px;
  --app-card-shadow-soft: 0 10px 24px rgba(15, 23, 42, 0.05);
  --app-page-title-size: 28px;
  --app-page-title-size-mobile: 24px;
  --app-page-subtitle-max-width: 760px;
  --app-page-subtitle-color: rgba(15, 23, 42, 0.68);
  --app-page-header-gap: 16px;
  --app-summary-card-background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
}

html, body, #app {
  margin: 0;
  padding: 0;
  height: 100%;
  font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  background: #f5f7fb;
}

body {
  color: #0f172a;
}

.app-loading {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
}

.app-shell {
  height: 100vh;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(32, 128, 240, 0.08), transparent 30%),
    linear-gradient(180deg, #f8fafc 0%, #f3f6fb 100%);
}

.app-shell__sider {
  position: sticky !important;
  top: 0;
  height: 100vh;
  background: rgba(255, 255, 255, 0.78);
  backdrop-filter: blur(12px);
  border-right: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
}

.app-shell__main,
.app-shell__content {
  background: transparent;
}

.app-shell__content-inner {
  max-width: var(--app-page-max-width);
  margin: 0 auto;
}

.app-shell__main {
  height: 100vh;
  overflow-y: auto;
}

.app-shell__content-inner {
  min-height: calc(100vh - 40px);
}

.app-shell__topbar-wrapper {
  width: min(calc(100% - 40px), var(--app-page-max-width));
  margin: 14px auto 0;
}

.app-shell__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
  padding: 12px 14px;
  border-radius: 18px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.08);
  box-shadow: 0 10px 24px rgba(15, 23, 42, 0.05);
}

.app-shell__topbar-user {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}

.app-shell__onboarding-button,
.app-shell__logout-button {
  flex-shrink: 0;
}

.app-shell__onboarding-button--icon-only {
  color: rgba(15, 23, 42, 0.5);
}

.app-shell__onboarding-button--icon-only:hover {
  color: rgba(15, 23, 42, 0.72);
}

/* Global button styling - unified rounded corners */
.n-button {
  border-radius: 10px !important;
  transition: all 0.2s ease;
}

.n-button.n-button--round {
  border-radius: 999px !important;
}

.n-button.n-button--circle {
  border-radius: 50% !important;
}

.app-shell__topbar-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.app-shell__announcement-banner {
  margin-bottom: 6px;
  overflow: hidden;
}

.app-shell__topbar-announcement-pill {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 4px 12px 4px 10px;
  border-radius: 10px;
  width: 100%;
  box-sizing: border-box;
  min-width: 0;
  overflow: hidden;
  transition: opacity 0.2s ease;
}

.app-shell__topbar-announcement-icon {
  flex-shrink: 0;
  opacity: 0.85;
}

/* Scrolling marquee container */
.app-shell__topbar-announcement-marquee {
  overflow: hidden;
  min-width: 0;
}

/* Only apply animation when text actually overflows */
.app-shell__topbar-announcement-text {
  display: inline-block;
  font-size: 12.5px;
  font-weight: 400;
  white-space: nowrap;
  line-height: 1.4;
}

.app-shell__topbar-announcement-marquee--scrolling .app-shell__topbar-announcement-text {
  animation: announcement-scroll 12s linear 2s infinite;
}

/* Pause on hover */
.app-shell__topbar-announcement-marquee--scrolling:hover .app-shell__topbar-announcement-text {
  animation-play-state: paused;
}

@keyframes announcement-scroll {
  0%, 15% {
    transform: translateX(0);
  }
  80%, 95% {
    transform: translateX(var(--scroll-offset, -60%));
  }
  100% {
    transform: translateX(0);
  }
}

.app-shell__topbar-announcement-pill--info {
  background: rgba(32, 128, 240, 0.08);
  border: 1px solid rgba(32, 128, 240, 0.2);
  color: #1565c7;
}

.app-shell__topbar-announcement-pill--warning {
  background: rgba(240, 160, 32, 0.1);
  border: 1px solid rgba(240, 160, 32, 0.28);
  color: #a06800;
}

.app-shell__topbar-announcement-pill--error {
  background: rgba(208, 48, 80, 0.08);
  border: 1px solid rgba(208, 48, 80, 0.22);
  color: #b81030;
}

.app-shell__topbar-announcement-pill--success {
  background: rgba(24, 160, 88, 0.08);
  border: 1px solid rgba(24, 160, 88, 0.22);
  color: #0d7a3e;
}

.app-shell__language-toggle {
  flex-shrink: 0;
}

.usage-indicator {
  flex-shrink: 0;
}

.usage-indicator--normal {
  color: #18a058;
}

.usage-indicator--near_limit {
  color: #f0a020;
}

.usage-indicator--over_limit {
  color: #d03050;
}

.usage-indicator__tooltip {
  min-width: 260px;
  color: rgba(255, 255, 255, 0.9);
}

.usage-indicator__tooltip-title {
  font-weight: 600;
  margin-bottom: 8px;
}

.usage-indicator__tooltip-row {
  margin-top: 6px;
}

.usage-indicator__tooltip-row-top {
  display: flex;
  justify-content: space-between;
  gap: 12px;
}

.usage-indicator__tooltip-row--reset {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  margin-top: 6px;
}

.usage-indicator__tooltip-label {
  flex-shrink: 0;
}

.usage-indicator__tooltip-value {
  text-align: right;
}

.usage-indicator__progress {
  height: 6px;
  border-radius: 3px;
  background: rgba(255, 255, 255, 0.15);
  margin-top: 4px;
  overflow: hidden;
}

.usage-indicator__progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.usage-indicator__progress-fill--normal {
  background: #18a058;
}

.usage-indicator__progress-fill--near_limit {
  background: #f0a020;
}

.usage-indicator__progress-fill--over_limit {
  background: #d03050;
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px;
  margin-bottom: 16px;
  border-radius: 18px;
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.12), rgba(32, 128, 240, 0.05));
  border: 1px solid rgba(32, 128, 240, 0.14);
}

.logo--collapsed {
  justify-content: center;
  width: 72px;
  margin-left: 0;
  margin-right: 0;
  padding: 0;
  background: transparent;
  border-color: transparent;
  box-shadow: none;
}

.logo__mark {
  width: 40px;
  height: 40px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 14px;
  background: linear-gradient(135deg, #2080f0, #36ad6a);
  color: #fff;
  box-shadow: 0 10px 20px rgba(32, 128, 240, 0.25);
  flex-shrink: 0;
}

.logo__mark--mobile {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  box-shadow: 0 8px 18px rgba(32, 128, 240, 0.18);
}

.logo__copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.logo__title {
  font-size: 16px;
  line-height: 1.2;
}

.logo__subtitle {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.3;
}

.nav-menu .n-menu-item-content,
.nav-menu .n-menu-item-content-header,
.nav-menu .n-menu-item-group-title {
  transition: all 0.2s ease;
}

.nav-menu .n-menu-item-group-title {
  margin-top: 14px;
  padding: 0 12px 4px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: rgba(15, 23, 42, 0.42);
}

.nav-menu .n-menu-item-content {
  border-radius: 14px;
  margin: 4px 0;
}

.nav-menu .n-menu-item-content--collapsed {
  width: 72px;
  min-height: 40px;
  padding-right: 0 !important;
  margin-left: 0;
  margin-right: 0;
}

.nav-menu .n-menu-item-content--collapsed .n-menu-item-content__icon {
  margin-right: 0 !important;
}

.nav-menu .n-menu-item-content::before {
  border-radius: 14px !important;
}

.nav-menu .n-menu-item-content--selected {
  background: linear-gradient(135deg, rgba(32, 128, 240, 0.18), rgba(32, 128, 240, 0.08));
  box-shadow: inset 0 0 0 1px rgba(32, 128, 240, 0.16);
}

.nav-menu .n-menu-item-content--selected .n-menu-item-content-header,
.nav-menu .n-menu-item-content--selected .n-icon {
  color: #1d4ed8;
  font-weight: 600;
}

.nav-menu .n-menu-item-content:hover {
  background: rgba(148, 163, 184, 0.12);
}

.nav-user-panel__identity {
  display: flex;
  align-items: center;
  gap: 10px;
}

.nav-user-panel__copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.nav-user-panel__role {
  font-size: 12px;
}

.mobile-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: 10px 12px 0;
  padding: 10px 12px;
  border-radius: 16px;
  border: 1px solid rgba(15, 23, 42, 0.06);
  background: rgba(255, 255, 255, 0.72);
  backdrop-filter: blur(10px);
  box-shadow: 0 6px 16px rgba(15, 23, 42, 0.04);
}

.mobile-header__left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
  flex: 1;
}

.mobile-header__menu-button {
  background: rgba(32, 128, 240, 0.08);
  color: #1d4ed8;
}

.mobile-header__copy {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.mobile-header__eyebrow {
  font-size: 11px;
  line-height: 1.2;
}

.mobile-header__title {
  margin-top: 1px;
  font-size: 15px;
  line-height: 1.2;
}

.mobile-header__badge {
  padding: 4px 8px;
  border-radius: 999px;
  background: rgba(32, 128, 240, 0.1);
  color: #1d4ed8;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
}

.mobile-header__language-toggle {
  flex-shrink: 0;
}

.mobile-header__actions {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

.mobile-header__user-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  max-width: 132px;
  padding: 4px 8px 4px 4px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.mobile-header__user-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 600;
  color: #0f172a;
}

.mobile-header__logout-button {
  color: #334155;
}

.mobile-drawer-header {
  padding: 2px 0 10px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.06);
}

.mobile-drawer-header__brand {
  display: flex;
  align-items: center;
  gap: 12px;
}

a.app-link {
  color: var(--n-text-color-1);
  text-decoration: none;
  border-bottom: 1px solid rgba(32, 128, 240, 0.24);
  transition: color 0.2s ease, border-color 0.2s ease, background-color 0.2s ease;
}

a.app-link:hover {
  color: #2080f0;
  border-bottom-color: rgba(32, 128, 240, 0.55);
}

a.app-link:active {
  color: #1a6fd9;
}

a.app-link:visited {
  color: var(--n-text-color-1);
}

a.app-link:visited:hover {
  color: #2080f0;
}

@media (max-width: 767px) {
  .app-shell__content-inner {
    min-height: calc(100vh - 28px);
  }

  .nav-menu .n-menu-item-content {
    margin: 2px 0;
    border-radius: 12px;
  }

  .mobile-header__user-chip {
    max-width: 112px;
  }
}

.app-footer {
  margin-top: 32px;
  padding: 12px 0;
  text-align: center;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
}

.app-footer__text {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.22);
}

.app-footer__link {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.28);
  text-decoration: none;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  transition: color 0.2s ease;
}

.app-footer__link:hover {
  color: rgba(15, 23, 42, 0.45);
}

.app-footer__icon {
  flex-shrink: 0;
}

@media (max-width: 480px) {
  .mobile-header {
    align-items: flex-start;
  }

  .mobile-header__actions {
    gap: 6px;
  }

  .mobile-header__user-name {
    display: none;
  }

  .mobile-header__user-chip {
    padding-right: 4px;
  }
}

/* ===================================================================
   Shared page hero section (gradient header + summary cards)
   =================================================================== */

.page-hero {
  position: relative;
  padding: 32px 36px 28px;
  margin: -16px -16px 16px;
  background:
    radial-gradient(ellipse 80% 60% at 20% 0%, rgba(99, 102, 241, 0.06), transparent 60%),
    radial-gradient(ellipse 60% 50% at 80% 100%, rgba(59, 130, 246, 0.05), transparent 55%),
    linear-gradient(180deg, rgba(248, 250, 252, 0.98) 0%, rgba(248, 250, 252, 0.4) 100%);
  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  overflow: hidden;
}

.page-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, rgba(15, 23, 42, 0.03) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
  mask-image: linear-gradient(180deg, black 0%, transparent 100%);
}

.page-hero > .n-grid {
  margin-top: 24px;
}

.page-hero .n-gi {
  display: flex;
}

.page-hero .n-gi > * {
  width: 100%;
}

@media (max-width: 767px) {
  .page-hero {
    padding: 20px 16px 20px;
    margin: -12px -12px 12px;
  }
}

/* Unified native scrollbar — thin, subtle, cross-platform consistent */
::-webkit-scrollbar {
  width: 6px;
  height: 6px;
}

::-webkit-scrollbar-track {
  background: transparent;
}

::-webkit-scrollbar-thumb {
  background: transparent;
  border-radius: 3px;
  transition: background 0.3s ease 0.1s;
}

html.is-scrolling ::-webkit-scrollbar-thumb {
  background: rgba(128, 128, 128, 0.3);
}

::-webkit-scrollbar-thumb:hover {
  background: rgba(128, 128, 128, 0.5) !important;
}

::-webkit-scrollbar-corner {
  background: transparent;
}

/* Popconfirm: additional padding via CSS */
.n-popover-body:has(.n-popconfirm) {
  padding: 16px 20px !important;
}
</style>
