<template>
  <n-config-provider :locale="naiveUiLocale" :date-locale="naiveUiDateLocale">
    <n-message-provider>
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
          <div v-if="showUserToolbar && !isMobile" class="app-shell__topbar">
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
              <LanguageToggle size="small" class="app-shell__language-toggle" />
              <n-button tertiary class="app-shell__logout-button" @click="handleLogout">
                <template #icon>
                  <n-icon :component="LogOutOutline" />
                </template>
                {{ t('shell.logout') }}
              </n-button>
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
            </div>
          </n-layout>
        </n-layout>
      </n-layout>
    </n-message-provider>
  </n-config-provider>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NAvatar,
  NButton,
  NConfigProvider,
  NDrawer,
  NDrawerContent,
  NIcon,
  NLayout,
  NLayoutSider,
  NMenu,
  NMessageProvider,
  NSpin,
  NText
} from 'naive-ui'
import type { MenuOption } from 'naive-ui'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  AddCircleOutline,
  BarChartOutline,
  FingerPrintOutline,
  GridOutline,
  LogOutOutline,
  MenuOutline,
  CalendarOutline,
  PeopleOutline,
  RocketOutline,
  SettingsOutline,
  SpeedometerOutline
} from '@vicons/ionicons5'
import { authState, canAccessSharedPage, initializeAuth, isAdmin, logoutAndClearAuth } from './auth'
import LanguageToggle from './components/LanguageToggle.vue'
import { useBreakpoints } from './composables/useBreakpoints'
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

const activeKey = computed(() => route.name as string)
const isLoginRoute = computed(() => route.name === 'Login')
const isBootstrapRoute = computed(() => route.name === 'Bootstrap')
const showShell = computed(() => !isLoginRoute.value && !isBootstrapRoute.value)

const menuLabels: Record<string, string> = {
  Dashboard: 'nav.dashboard',
  CreateTask: 'nav.createTask',
  Sessions: 'nav.sessions',
  Monitor: 'nav.monitor',
  ScheduleOverview: 'nav.scheduleOverview',
  Analytics: 'nav.analytics',
  Config: 'nav.config',
  AccessManagement: 'nav.accessManagement'
}

const currentPageLabel = computed(() => t(menuLabels[activeKey.value] || 'app.navigation'))
const showUserToolbar = computed(() => authState.authenticated)
const userDisplayName = computed(
  () => authState.user?.display_name || authState.user?.username || t('shell.gitlabUser')
)
const userInitial = computed(() => userDisplayName.value.slice(0, 1).toUpperCase())
const renderIcon = (icon: any) => () => h(NIcon, null, { default: () => h(icon) })
const shouldGroupMenu = computed(() => !collapsed.value || isMobile.value)

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
    buildMenuItem('nav.createTask', 'CreateTask', AddCircleOutline)
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

async function handleLogout() {
  await logoutAndClearAuth()
}

onMounted(() => {
  initializeAuth()
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
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
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

.app-shell__topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: min(calc(100% - 40px), var(--app-page-max-width));
  margin: 14px auto 0;
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

.app-shell__logout-button {
  flex-shrink: 0;
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

.app-shell__language-toggle {
  flex-shrink: 0;
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
</style>
