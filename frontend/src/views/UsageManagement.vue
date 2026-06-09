<template>
  <div class="usage-page" data-testid="usage-management-page">
    <!-- Hero Section -->
    <div class="usage-hero">
      <PageHeader
        :title="t('usageManagement.title')"
        :subtitle="t('usageManagement.subtitle')"
        root-class="usage-page__hero"
        title-class="usage-page__title"
        subtitle-class="usage-page__subtitle"
      >
        <template #actions>
          <n-button
            size="small"
            quaternary
            @click="fetchUsageManagement"
            :loading="loading"
            :disabled="loading"
          >
            <template #icon>
              <n-icon :component="RefreshOutline" :size="16" />
            </template>
            {{ t('usageManagement.reload') }}
          </n-button>
        </template>
      </PageHeader>

      <!-- Summary stat blocks -->
      <div class="usage-stats" :class="{ 'usage-stats--visible': hasLoadedOnce }">
        <div
          v-for="item in summaryItems"
          :key="item.label"
          class="usage-stat"
          :class="`usage-stat--${item.key}`"
        >
          <div class="usage-stat__icon-ring">
            <n-icon :component="item.icon" :size="20" />
          </div>
          <div class="usage-stat__body">
            <span class="usage-stat__value">{{ item.value }}</span>
            <span class="usage-stat__label">{{ item.label }}</span>
          </div>
        </div>
      </div>
    </div>

    <n-alert type="info" :show-icon="false" class="usage-intro">
      {{ t('usageManagement.intro') }}
    </n-alert>

    <n-spin :show="loading && !hasLoadedOnce" :description="t('usageManagement.loading')">
      <!-- System Defaults -->
      <n-card class="usage-card usage-card--defaults" :bordered="false">
        <template #header>
          <div class="usage-card__header">
            <div>
              <div class="usage-card__title">{{ t('usageManagement.systemDefaults') }}</div>
              <div class="usage-card__subtitle">{{ t('usageManagement.intro') }}</div>
            </div>
            <div v-if="users.length" class="usage-management-card__header-resets">
              <span class="usage-card__reset-chip">
                <n-icon :component="TimeOutline" :size="13" />
                {{ formatUsageResetAt(users[0].reset_at.daily) }}
              </span>
              <span class="usage-card__reset-chip">
                <n-icon :component="CalendarClearOutline" :size="13" />
                {{ formatUsageResetAt(users[0].reset_at.weekly) }}
              </span>
            </div>
          </div>
        </template>

        <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="12">
          <n-gi v-for="field in limitFields" :key="field.key">
            <div class="usage-field">
              <label class="usage-field__label">{{ field.label }}</label>
              <div class="usage-limit-row">
                <n-select
                  :value="defaultDraft[field.key].mode"
                  :options="defaultModeOptions"
                  size="small"
                  class="usage-limit-row__mode"
                  @update:value="(value: any) => updateDefaultMode(field.key, value)"
                />
                <n-input-number
                  v-model:value="defaultDraft[field.key].value"
                  :min="1"
                  size="small"
                  :disabled="defaultDraft[field.key].mode !== 'custom'"
                  class="usage-limit-row__value"
                />
              </div>
            </div>
          </n-gi>
        </n-grid>

        <template #action>
          <div class="usage-card__actions">
            <n-button
              size="small"
              type="primary"
              data-testid="usage-management-save-defaults"
              :loading="savingDefault"
              :disabled="!isDefaultDirty"
              @click="handleSaveDefault"
            >
              {{ t('usageManagement.saveDefaults') }}
            </n-button>
          </div>
        </template>
      </n-card>

      <!-- User Overrides -->
      <n-card class="usage-card usage-card--users" :bordered="false">
        <template #header>
          <div class="usage-card__header">
            <div>
              <div class="usage-card__title">{{ t('usageManagement.userOverrides') }}</div>
              <div class="usage-card__subtitle">{{ t('usageManagement.subtitle') }}</div>
            </div>
            <div class="usage-filter-bar">
              <div class="usage-filter-bar__search">
                <n-icon :component="SearchOutline" :size="15" class="usage-filter-bar__search-icon" />
                <input
                  v-model="searchQuery"
                  :placeholder="t('usageManagement.searchPlaceholder')"
                  class="usage-filter-bar__search-input"
                />
                <button
                  v-if="searchQuery"
                  class="usage-filter-bar__search-clear"
                  @click="searchQuery = ''"
                >
                  <n-icon :component="CloseOutline" :size="13" />
                </button>
              </div>
              <div class="usage-filter-bar__pills">
                <button
                  v-for="opt in filterModeOptions"
                  :key="opt.value"
                  class="usage-filter-pill"
                  :class="{ 'usage-filter-pill--active': filterMode === opt.value }"
                  @click="filterMode = opt.value as 'all' | 'overridden' | 'not_overridden'"
                >
                  {{ opt.label }}
                </button>
              </div>
            </div>
          </div>
        </template>

        <!-- User grid -->
        <div class="usage-user-grid">
          <div
            v-for="(user, index) in filteredUsers"
            :key="user.user_id"
            class="usage-user-card"
            data-testid="usage-management-user-card"
            :style="{ animationDelay: `${index * 50}ms` }"
          >
            <!-- Card head -->
            <div class="usage-management-user-card__head">
              <div class="usage-user-card__avatar">
                {{ (user.display_name || user.username).charAt(0).toUpperCase() }}
              </div>
              <div class="usage-user-card__identity">
                <span class="usage-management-user-card__name">{{ user.display_name || user.username }}</span>
                <span class="usage-management-user-card__meta">@{{ user.username }}</span>
              </div>
              <span v-if="hasUserOverride(user)" class="usage-management-user-card__badge">
                {{ t('usageManagement.overridden') }}
              </span>
            </div>

            <!-- Card body -->
            <div class="usage-management-user-card__body">
              <div
                v-for="field in limitFields"
                :key="`${user.user_id}-${field.key}`"
                class="usage-management-user-card__field"
              >
                <div class="usage-management-user-card__field-label">{{ field.label }}</div>

                <!-- Usage vs limit with progress bar -->
                <div class="usage-management-user-card__field-usage">
                  <span class="usage-management-user-card__field-used">
                    {{ formatLargeNumber(user.usage[field.key]) }}
                  </span>
                  <span class="usage-management-user-card__field-limit">
                    / {{ formatLimitValue(user.limits[field.key]) }}
                  </span>
                </div>
                <div
                  class="usage-progress"
                  :class="[`usage-progress--${usageSeverity(user, field.key)}`, { 'usage-progress--unlimited': usagePercent(user, field.key) === null }]"
                >
                  <div
                    class="usage-progress__bar"
                    :style="{ width: usagePercent(user, field.key) !== null ? `${Math.min(usagePercent(user, field.key)!, 100)}%` : '0%' }"
                  />
                </div>

                <!-- Override controls -->
                <div class="usage-management-user-card__field-override">
                  <n-select
                    :value="userDrafts[user.user_id][field.key].mode"
                    :options="userModeOptions"
                    size="tiny"
                    class="usage-limit-row__mode"
                    @update:value="(value: any) => updateUserMode(user.user_id, field.key, value)"
                  />
                  <n-input-number
                    v-model:value="userDrafts[user.user_id][field.key].value"
                    :min="1"
                    size="tiny"
                    :disabled="userDrafts[user.user_id][field.key].mode !== 'custom'"
                    class="usage-limit-row__value"
                  />
                </div>
              </div>
            </div>

            <!-- Card foot -->
            <div class="usage-management-user-card__foot">
              <n-button
                size="tiny"
                type="primary"
                secondary
                data-testid="usage-management-save-user"
                :loading="isUserSaving(user.user_id)"
                :disabled="!isUserDirty(user)"
                @click="handleSaveUser(user)"
              >
                {{ t('usageManagement.saveUser') }}
              </n-button>
            </div>
          </div>
        </div>
      </n-card>
    </n-spin>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NGi,
  NGrid,
  NIcon,
  NInputNumber,
  NSelect,
  NSpin,
  useMessage,
} from 'naive-ui'
import {
  PeopleOutline,
  SettingsOutline,
  WarningOutline,
  RefreshOutline,
  TimeOutline,
  CalendarClearOutline,
  SearchOutline,
  CloseOutline,
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import {
  getAdminUsageLimitDefault,
  listAdminUsageLimitUsers,
  updateAdminUsageLimitDefault,
  updateAdminUsageLimitUser,
  type AdminUsageLimitDefaultUpdateRequest,
  type AdminUsageLimitPolicy,
  type AdminUsageLimitUserRow,
  type AdminUsageLimitUserUpdateRequest,
  type UsageLimitValue,
} from '../api'
import PageHeader from '../components/PageHeader.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatLargeNumber, formatUsageResetAt } from '../utils/usageLimits'

type LimitFieldKey = keyof AdminUsageLimitPolicy

const limitFieldOrder: LimitFieldKey[] = ['daily_tokens', 'weekly_tokens', 'daily_tasks', 'weekly_tasks']

const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

const loading = ref(false)
const hasLoadedOnce = ref(false)
const savingDefault = ref(false)
const savingUserIds = ref<number[]>([])
const searchQuery = ref('')
const filterMode = ref<'all' | 'overridden' | 'not_overridden'>('all')

const defaultPolicy = ref<AdminUsageLimitPolicy | null>(null)
const defaultDraft = ref<AdminUsageLimitDefaultUpdateRequest>(createEmptyDefaultDraft())
const users = ref<AdminUsageLimitUserRow[]>([])
const userDrafts = ref<Record<number, AdminUsageLimitUserUpdateRequest>>({})

const limitFields = computed(() => [
  { key: 'daily_tokens' as const, label: t('shell.dailyTokens') },
  { key: 'weekly_tokens' as const, label: t('shell.weeklyTokens') },
  { key: 'daily_tasks' as const, label: t('shell.dailyTasks') },
  { key: 'weekly_tasks' as const, label: t('shell.weeklyTasks') },
])

const defaultModeOptions = computed(() => [
  { label: t('usageManagement.modeCustom'), value: 'custom' },
  { label: t('usageManagement.modeUnlimited'), value: 'unlimited' },
])

const userModeOptions = computed(() => [
  { label: t('usageManagement.modeInherit'), value: 'inherit' },
  { label: t('usageManagement.modeCustom'), value: 'custom' },
  { label: t('usageManagement.modeUnlimited'), value: 'unlimited' },
])

const filterModeOptions = computed(() => [
  { label: t('usageManagement.filterAll'), value: 'all' },
  { label: t('usageManagement.filterOverridden'), value: 'overridden' },
  { label: t('usageManagement.filterNotOverridden'), value: 'not_overridden' },
])

function hasUserOverride(user: AdminUsageLimitUserRow): boolean {
  return limitFieldOrder.some((field) => user.overrides[field].mode !== 'inherit')
}

function usagePercent(user: AdminUsageLimitUserRow, field: LimitFieldKey): number | null {
  const limit = user.limits[field]
  if (limit.mode === 'unlimited' || limit.value === null || limit.value === 0) return null
  return (user.usage[field] / limit.value) * 100
}

function usageSeverity(user: AdminUsageLimitUserRow, field: LimitFieldKey): 'low' | 'mid' | 'high' {
  const pct = usagePercent(user, field)
  if (pct === null) return 'low'
  if (pct >= 85) return 'high'
  if (pct >= 60) return 'mid'
  return 'low'
}

const filteredUsers = computed(() => {
  let result = users.value

  const search = searchQuery.value.trim().toLowerCase()
  if (search) {
    result = result.filter((user) =>
      [user.username, user.display_name || ''].join(' ').toLowerCase().includes(search)
    )
  }

  if (filterMode.value === 'overridden') {
    result = result.filter((user) => hasUserOverride(user))
  } else if (filterMode.value === 'not_overridden') {
    result = result.filter((user) => !hasUserOverride(user))
  }

  return result
})

const summaryItems = computed(() => {
  const customOverrideUsers = users.value.filter((user) =>
    limitFieldOrder.some((field) => user.overrides[field].mode !== 'inherit')
  ).length
  const overLimitUsers = users.value.filter((user) =>
    limitFieldOrder.some((field) => {
      const limit = user.limits[field]
      return limit.mode !== 'unlimited' && limit.value !== null && user.usage[field] > limit.value
    })
  ).length

  return [
    { key: 'total', label: t('usageManagement.totalUsers'), value: String(users.value.length), icon: PeopleOutline },
    { key: 'overrides', label: t('usageManagement.customOverrideUsers'), value: String(customOverrideUsers), icon: SettingsOutline },
    { key: 'overlimit', label: t('usageManagement.overLimitUsers'), value: String(overLimitUsers), icon: WarningOutline },
  ]
})

const isDefaultDirty = computed(() => {
  if (!defaultPolicy.value) {
    return false
  }
  return JSON.stringify(defaultDraft.value) !== JSON.stringify(toDefaultDraft(defaultPolicy.value))
})

function createEmptyDefaultDraft(): AdminUsageLimitDefaultUpdateRequest {
  return {
    daily_tokens: { mode: 'unlimited', value: null },
    weekly_tokens: { mode: 'unlimited', value: null },
    daily_tasks: { mode: 'unlimited', value: null },
    weekly_tasks: { mode: 'unlimited', value: null },
  }
}

function clonePolicyValue<T extends UsageLimitValue['mode']>(value: { mode: T; value: number | null }) {
  return {
    mode: value.mode,
    value: value.value,
  }
}

function normalizeModeValue<T extends UsageLimitValue['mode']>(mode: T, value: number | null) {
  if (mode === 'custom') {
    return {
      mode,
      value: value && value > 0 ? value : 1,
    }
  }

  return {
    mode,
    value: null,
  }
}

function toDefaultDraft(policy: AdminUsageLimitPolicy): AdminUsageLimitDefaultUpdateRequest {
  return {
    daily_tokens: clonePolicyValue(policy.daily_tokens as { mode: 'custom' | 'unlimited'; value: number | null }),
    weekly_tokens: clonePolicyValue(policy.weekly_tokens as { mode: 'custom' | 'unlimited'; value: number | null }),
    daily_tasks: clonePolicyValue(policy.daily_tasks as { mode: 'custom' | 'unlimited'; value: number | null }),
    weekly_tasks: clonePolicyValue(policy.weekly_tasks as { mode: 'custom' | 'unlimited'; value: number | null }),
  }
}

function toUserDraft(policy: AdminUsageLimitPolicy): AdminUsageLimitUserUpdateRequest {
  return {
    daily_tokens: clonePolicyValue(policy.daily_tokens),
    weekly_tokens: clonePolicyValue(policy.weekly_tokens),
    daily_tasks: clonePolicyValue(policy.daily_tasks),
    weekly_tasks: clonePolicyValue(policy.weekly_tasks),
  }
}

function sanitizeDefaultDraft(draft: AdminUsageLimitDefaultUpdateRequest): AdminUsageLimitDefaultUpdateRequest {
  return {
    daily_tokens: normalizeModeValue(draft.daily_tokens.mode, draft.daily_tokens.value),
    weekly_tokens: normalizeModeValue(draft.weekly_tokens.mode, draft.weekly_tokens.value),
    daily_tasks: normalizeModeValue(draft.daily_tasks.mode, draft.daily_tasks.value),
    weekly_tasks: normalizeModeValue(draft.weekly_tasks.mode, draft.weekly_tasks.value),
  }
}

function sanitizeUserDraft(draft: AdminUsageLimitUserUpdateRequest): AdminUsageLimitUserUpdateRequest {
  return {
    daily_tokens: normalizeModeValue(draft.daily_tokens.mode, draft.daily_tokens.value),
    weekly_tokens: normalizeModeValue(draft.weekly_tokens.mode, draft.weekly_tokens.value),
    daily_tasks: normalizeModeValue(draft.daily_tasks.mode, draft.daily_tasks.value),
    weekly_tasks: normalizeModeValue(draft.weekly_tasks.mode, draft.weekly_tasks.value),
  }
}

function updateDefaultMode(field: LimitFieldKey, mode: AdminUsageLimitDefaultUpdateRequest[LimitFieldKey]['mode']) {
  defaultDraft.value = {
    ...defaultDraft.value,
    [field]: normalizeModeValue(mode, defaultDraft.value[field].value),
  }
}

function updateUserMode(
  userId: number,
  field: LimitFieldKey,
  mode: AdminUsageLimitUserUpdateRequest[LimitFieldKey]['mode']
) {
  userDrafts.value = {
    ...userDrafts.value,
    [userId]: {
      ...userDrafts.value[userId],
      [field]: normalizeModeValue(mode, userDrafts.value[userId][field].value),
    },
  }
}

function syncUserDrafts(items: AdminUsageLimitUserRow[]) {
  userDrafts.value = Object.fromEntries(items.map((user) => [user.user_id, toUserDraft(user.overrides)]))
}

function formatLimitValue(limit: UsageLimitValue) {
  if (limit.mode === 'unlimited' || limit.value === null) {
    return t('shell.usageUnlimited')
  }
  return formatLargeNumber(limit.value)
}

function setUserSaving(userId: number, active: boolean) {
  savingUserIds.value = active
    ? Array.from(new Set([...savingUserIds.value, userId]))
    : savingUserIds.value.filter((id) => id !== userId)
}

function isUserSaving(userId: number) {
  return savingUserIds.value.includes(userId)
}

function isUserDirty(user: AdminUsageLimitUserRow) {
  return JSON.stringify(userDrafts.value[user.user_id]) !== JSON.stringify(toUserDraft(user.overrides))
}

async function fetchUsageManagement() {
  loading.value = true
  try {
    const [policy, userRows] = await Promise.all([
      getAdminUsageLimitDefault(),
      listAdminUsageLimitUsers(),
    ])
    defaultPolicy.value = policy
    defaultDraft.value = toDefaultDraft(policy)
    users.value = userRows
    syncUserDrafts(userRows)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('usageManagement.failedToLoad'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

async function handleSaveDefault() {
  savingDefault.value = true
  try {
    const payload = sanitizeDefaultDraft(defaultDraft.value)
    const updatedPolicy = await updateAdminUsageLimitDefault(payload)
    defaultPolicy.value = updatedPolicy
    defaultDraft.value = toDefaultDraft(updatedPolicy)
    users.value = await listAdminUsageLimitUsers()
    syncUserDrafts(users.value)
    message.success(t('usageManagement.savedDefaults'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('usageManagement.failedToSaveDefaults'))
  } finally {
    savingDefault.value = false
  }
}

async function handleSaveUser(user: AdminUsageLimitUserRow) {
  setUserSaving(user.user_id, true)
  try {
    const payload = sanitizeUserDraft(userDrafts.value[user.user_id])
    const updatedUser = await updateAdminUsageLimitUser(user.user_id, payload)
    users.value = users.value.map((item) => (item.user_id === updatedUser.user_id ? updatedUser : item))
    userDrafts.value = {
      ...userDrafts.value,
      [updatedUser.user_id]: toUserDraft(updatedUser.overrides),
    }
    message.success(t('usageManagement.savedUser', { username: updatedUser.username }))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('usageManagement.failedToSaveUser'))
  } finally {
    setUserSaving(user.user_id, false)
  }
}

onMounted(() => {
  fetchUsageManagement()
})
</script>

<style scoped>
/* ===================================================================
   Page Shell
   =================================================================== */

.usage-page {
  max-width: var(--app-page-max-width);
}

/* ===================================================================
   Hero Section
   =================================================================== */

.usage-hero {
  position: relative;
  padding: 32px 36px 28px;
  margin: -16px -16px 16px;

  border-bottom: 1px solid rgba(15, 23, 42, 0.05);
  overflow: hidden;
}

.usage-hero::before {
  content: '';
  position: absolute;
  inset: 0;
  background-image: radial-gradient(circle, rgba(15, 23, 42, 0.03) 1px, transparent 1px);
  background-size: 20px 20px;
  pointer-events: none;
  mask-image: linear-gradient(180deg, black 0%, transparent 100%);
}

.usage-page__title {
  font-size: var(--app-page-title-size, 28px) !important;
  font-weight: 700 !important;
  letter-spacing: -0.02em !important;
}

.usage-page__subtitle {
  max-width: 600px !important;
}

/* ===================================================================
   Summary Stat Blocks
   =================================================================== */

.usage-stats {
  display: flex;
  gap: 12px;
  margin-top: 24px;
  position: relative;
  z-index: 1;
  opacity: 0;
  transition: opacity 0.25s ease;
}

.usage-stats--visible {
  opacity: 1;
}

.usage-stat {
  flex: 1;
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 16px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition:
    box-shadow 0.25s ease,
    border-color 0.25s ease;
}

.usage-stat:hover {
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.1);
}

.usage-stat__icon-ring {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.55);
}

.usage-stat--total .usage-stat__icon-ring {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.usage-stat--overrides .usage-stat__icon-ring {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.usage-stat--overlimit .usage-stat__icon-ring {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.usage-stat__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.usage-stat__value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.2;
  color: #0f172a;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.usage-stat__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.52);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* ===================================================================
   Intro Alert
   =================================================================== */

.usage-intro {
  margin-top: 16px;
  border-radius: 12px !important;
  background: rgba(59, 130, 246, 0.04) !important;
  border: 1px solid rgba(59, 130, 246, 0.1) !important;
}

.usage-intro :deep(.n-alert-body) {
  font-size: 13px !important;
  color: rgba(15, 23, 42, 0.65) !important;
}

/* ===================================================================
   Cards (System Defaults & User Overrides)
   =================================================================== */

.usage-card {
  margin-top: 16px;
  border-radius: 16px !important;
  background: rgba(255, 255, 255, 0.8) !important;
  backdrop-filter: blur(16px);
  border: 1px solid rgba(15, 23, 42, 0.06) !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition: box-shadow 0.3s ease;
  overflow: hidden;
}

.usage-card:hover {
  box-shadow: 0 4px 20px rgba(15, 23, 42, 0.07);
}

.usage-card :deep(.n-card__content) {
  padding: 18px;
}

.usage-card :deep(.n-card__header) {
  padding: 16px 18px 0;
}

.usage-card :deep(.n-card__action) {
  border-radius: 0 0 16px 16px;
}

.usage-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  flex-wrap: wrap;
}

.usage-card__title {
  font-size: 16px;
  font-weight: 650;
  color: #0f172a;
  letter-spacing: -0.01em;
}

.usage-card__subtitle {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.48);
}

.usage-card__reset-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  border-radius: 6px;
  font-size: 11px;
  color: rgba(15, 23, 42, 0.5);
  background: rgba(15, 23, 42, 0.03);
}

.usage-card__reset-chip + .usage-card__reset-chip {
  margin-left: 8px;
}

.usage-management-card__header-resets {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.usage-card__actions {
  display: flex;
  justify-content: flex-end;
  padding: 0 18px 14px;
}

/* ===================================================================
   Form Fields (System Defaults)
   =================================================================== */

.usage-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.usage-field__label {
  font-size: 12px;
  font-weight: 550;
  color: rgba(15, 23, 42, 0.55);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.usage-limit-row {
  display: flex;
  gap: 8px;
  width: 100%;
}

.usage-limit-row__mode {
  width: 96px;
  flex-shrink: 0;
}

.usage-limit-row__value {
  flex: 1;
  min-width: 0;
}

/* ===================================================================
   Filter Bar
   =================================================================== */

.usage-filter-bar {
  display: flex;
  gap: 8px;
  align-items: center;
  width: fit-content;
  padding: 6px 8px;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.06);
}

.usage-filter-bar__search {
  position: relative;
  display: flex;
  align-items: center;
  width: 220px;
  height: 30px;
}

.usage-filter-bar__search-icon {
  position: absolute;
  left: 10px;
  color: rgba(15, 23, 42, 0.35);
  pointer-events: none;
}

.usage-filter-bar__search-input {
  width: 100%;
  height: 100%;
  padding: 0 30px 0 32px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.7);
  font-size: 12px;
  font-family: inherit;
  color: #0f172a;
  outline: none;
  transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.usage-filter-bar__search-input::placeholder {
  color: rgba(15, 23, 42, 0.35);
}

.usage-filter-bar__search-input:focus {
  border-color: rgba(59, 130, 246, 0.4);
  box-shadow: 0 0 0 2px rgba(59, 130, 246, 0.1);
}

.usage-filter-bar__search-clear {
  position: absolute;
  right: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: rgba(15, 23, 42, 0.35);
  cursor: pointer;
  transition: background 0.15s ease, color 0.15s ease;
}

.usage-filter-bar__search-clear:hover {
  background: rgba(15, 23, 42, 0.06);
  color: rgba(15, 23, 42, 0.6);
}

.usage-filter-bar__pills {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}

.usage-filter-pill {
  height: 30px;
  padding: 0 14px;
  border: 1px solid rgba(15, 23, 42, 0.1);
  border-radius: 8px;
  background: transparent;
  font-size: 12px;
  font-weight: 500;
  line-height: 28px;
  color: rgba(15, 23, 42, 0.55);
  cursor: pointer;
  transition:
    background 0.2s ease,
    color 0.2s ease,
    border-color 0.2s ease,
    box-shadow 0.2s ease;
  white-space: nowrap;
  font-family: inherit;
  box-sizing: border-box;
}

.usage-filter-pill:hover {
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.75);
}

.usage-filter-pill--active {
  background: #0f172a !important;
  color: #fff !important;
  border-color: #0f172a !important;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.15);
}

/* ===================================================================
   User Grid & Cards
   =================================================================== */

.usage-user-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.usage-user-card {
  padding: 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.7);
  border: 1px solid rgba(15, 23, 42, 0.05);
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition:
    transform 0.25s cubic-bezier(0.22, 0.61, 0.36, 1),
    box-shadow 0.25s ease,
    border-color 0.25s ease;
  animation: card-enter 0.45s cubic-bezier(0.22, 0.61, 0.36, 1) both;
}

.usage-user-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.1);
}

@keyframes card-enter {
  from {
    opacity: 0;
    transform: translateY(16px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}

/* Head */

.usage-management-user-card__head {
  display: flex;
  align-items: center;
  gap: 10px;
}

.usage-user-card__avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 10px;
  background: linear-gradient(135deg, rgba(99, 102, 241, 0.15), rgba(59, 130, 246, 0.1));
  color: #4f46e5;
  font-size: 14px;
  font-weight: 650;
  letter-spacing: -0.01em;
}

.usage-user-card__identity {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}

.usage-management-user-card__name {
  font-size: 13px;
  font-weight: 600;
  color: #0f172a;
  line-height: 1.2;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.usage-management-user-card__meta {
  color: rgba(15, 23, 42, 0.42);
  font-size: 11px;
  line-height: 1.2;
}

.usage-management-user-card__badge {
  margin-left: auto;
  padding: 2px 8px;
  border-radius: 5px;
  background: rgba(99, 102, 241, 0.1);
  color: #4f46e5;
  font-size: 10px;
  font-weight: 600;
  flex-shrink: 0;
  letter-spacing: 0.02em;
}

/* Body */

.usage-management-user-card__body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px 8px;
}

.usage-management-user-card__field {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.usage-management-user-card__field-label {
  font-size: 10px;
  color: rgba(15, 23, 42, 0.45);
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-weight: 550;
}

.usage-management-user-card__field-usage {
  display: flex;
  align-items: baseline;
  gap: 4px;
}

.usage-management-user-card__field-used {
  font-size: 15px;
  font-weight: 650;
  color: #0f172a;
  letter-spacing: -0.01em;
  font-variant-numeric: tabular-nums;
}

.usage-management-user-card__field-limit {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.45);
}

/* Progress bars */

.usage-progress {
  height: 3px;
  border-radius: 2px;
  background: rgba(15, 23, 42, 0.06);
  overflow: hidden;
}

.usage-progress__bar {
  height: 100%;
  border-radius: 2px;
  transition: width 0.6s cubic-bezier(0.22, 0.61, 0.36, 1);
}

.usage-progress--low .usage-progress__bar {
  background: linear-gradient(90deg, #3b82f6, #6366f1);
}

.usage-progress--mid .usage-progress__bar {
  background: linear-gradient(90deg, #f59e0b, #f97316);
}

.usage-progress--high .usage-progress__bar {
  background: linear-gradient(90deg, #ef4444, #f43f5e);
}

.usage-progress--unlimited .usage-progress__bar {
  width: 100% !important;
  background: rgba(15, 23, 42, 0.05);
}

/* Override controls in user cards */

.usage-management-user-card__field-override {
  display: flex;
  gap: 4px;
  margin-top: 2px;
}

/* Foot */

.usage-management-user-card__foot {
  display: flex;
  justify-content: flex-end;
  padding-top: 2px;
  border-top: 1px solid rgba(15, 23, 42, 0.04);
}

/* ===================================================================
   Responsive
   =================================================================== */

@media (max-width: 1199px) {
  .usage-stats {
    flex-wrap: wrap;
  }

  .usage-stat {
    flex: 1 1 calc(50% - 6px);
  }
}

@media (max-width: 767px) {
  .usage-hero {
    padding: 20px 16px 20px;
    margin: -12px -12px 12px;
  }

  .usage-stats {
    flex-direction: column;
  }

  .usage-stat {
    flex: 1 1 100%;
  }

  .usage-user-grid {
    grid-template-columns: 1fr;
  }

  .usage-filter-bar {
    flex-direction: column;
    align-items: stretch;
  }

  .usage-filter-bar__pills {
    justify-content: flex-start;
  }

  .usage-card__header {
    flex-direction: column;
    gap: 8px;
  }

  .usage-filter-bar {
    width: 100%;
    flex-wrap: wrap;
  }

  .usage-management-card__header-resets {
    flex-direction: column;
    gap: 4px;
  }
}

@media (hover: none) {
  .usage-user-card:hover {
    transform: none;
    box-shadow: none;
  }

  .usage-stat:hover {
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  }
}
</style>

<style>
/* Usage management — select dropdown popover (teleported to body, must be unscoped) */
.n-base-select-option__content {
  font-size: 12px;
}

.n-base-select-option {
  padding: 4px 10px;
  min-height: unset;
}
</style>
