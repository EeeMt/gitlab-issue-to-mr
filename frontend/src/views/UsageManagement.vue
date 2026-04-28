<template>
  <div class="usage-management-page" data-testid="usage-management-page">
    <n-space vertical :size="16">
      <PageHeader
        :title="t('usageManagement.title')"
        :subtitle="t('usageManagement.subtitle')"
        root-class="usage-management-page__hero"
        title-class="usage-management-page__title"
        subtitle-class="usage-management-page__subtitle"
      >
        <template #actions>
          <n-button @click="fetchUsageManagement" :loading="loading" :disabled="loading">
            {{ t('usageManagement.reload') }}
          </n-button>
        </template>
      </PageHeader>

      <n-alert type="info" :show-icon="false">
        {{ t('usageManagement.intro') }}
      </n-alert>

      <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <SummaryCard
            :label="item.label"
            :value="item.value"
            card-class="usage-management-summary-card"
            label-class="usage-management-summary-card__label"
            value-class="usage-management-summary-card__value"
          />
        </n-gi>
      </n-grid>

      <n-spin :show="loading && !hasLoadedOnce" :description="t('usageManagement.loading')">
        <n-card class="usage-management-card" :bordered="false">
          <template #header>
            <div class="usage-management-card__header">
              <div class="usage-management-card__title">{{ t('usageManagement.systemDefaults') }}</div>
            </div>
          </template>

          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="12">
            <n-gi v-for="field in limitFields" :key="field.key">
              <n-form-item :label="field.label">
                <div class="usage-management-limit-row">
                  <n-select
                    :value="defaultDraft[field.key].mode"
                    :options="defaultModeOptions"
                    class="usage-management-limit-row__mode"
                    @update:value="(value) => updateDefaultMode(field.key, value)"
                  />
                  <n-input-number
                    v-model:value="defaultDraft[field.key].value"
                    :min="1"
                    :disabled="defaultDraft[field.key].mode !== 'custom'"
                    class="usage-management-limit-row__value"
                  />
                </div>
              </n-form-item>
            </n-gi>
          </n-grid>

          <template #action>
            <n-space justify="end">
              <n-button
                type="primary"
                data-testid="usage-management-save-defaults"
                :loading="savingDefault"
                :disabled="!isDefaultDirty"
                @click="handleSaveDefault"
              >
                {{ t('usageManagement.saveDefaults') }}
              </n-button>
            </n-space>
          </template>
        </n-card>

        <n-card class="usage-management-card" :bordered="false">
          <template #header>
            <div class="usage-management-card__header">
              <div class="usage-management-card__title">{{ t('usageManagement.userOverrides') }}</div>
            </div>
          </template>

          <n-input
            v-model:value="searchQuery"
            :placeholder="t('usageManagement.searchPlaceholder')"
            class="usage-management-search"
          />

          <div class="usage-management-user-grid">
            <n-card
              v-for="user in filteredUsers"
              :key="user.user_id"
              size="small"
              :bordered="false"
              class="usage-management-user-card"
              data-testid="usage-management-user-card"
            >
              <div class="usage-management-user-card__top">
                <div>
                  <div class="usage-management-user-card__name-row">
                    <div class="usage-management-user-card__name">{{ user.display_name || user.username }}</div>
                    <div class="usage-management-user-card__meta">@{{ user.username }}</div>
                  </div>
                </div>
                <div class="usage-management-user-card__reset">
                  <div class="usage-management-user-card__reset-item">
                    <span class="usage-management-user-card__label">{{ t('usageManagement.dailyReset') }}</span>
                    <span>{{ formatUsageResetAt(user.reset_at.daily) }}</span>
                  </div>
                  <div class="usage-management-user-card__reset-item">
                    <span class="usage-management-user-card__label">{{ t('usageManagement.weeklyReset') }}</span>
                    <span>{{ formatUsageResetAt(user.reset_at.weekly) }}</span>
                  </div>
                </div>
              </div>

              <div class="usage-management-user-card__stats">
                <div
                  v-for="field in limitFields"
                  :key="`${user.user_id}-${field.key}`"
                  class="usage-management-user-card__stat"
                >
                  <div class="usage-management-user-card__label">{{ field.label }}</div>
                  <div class="usage-management-user-card__stat__value">{{ user.usage[field.key] }}</div>
                  <div class="usage-management-user-card__stat-limit">
                    {{ formatLimitValue(user.limits[field.key]) }}
                  </div>
                </div>
              </div>

              <n-grid :cols="isMobile ? 1 : 2" :x-gap="12" :y-gap="8">
                <n-gi v-for="field in limitFields" :key="`${user.user_id}-${field.key}-override`">
                  <n-form-item :label="field.label">
                    <div class="usage-management-limit-row">
                      <n-select
                        :value="userDrafts[user.user_id][field.key].mode"
                        :options="userModeOptions"
                        class="usage-management-limit-row__mode"
                        @update:value="(value) => updateUserMode(user.user_id, field.key, value)"
                      />
                      <n-input-number
                        v-model:value="userDrafts[user.user_id][field.key].value"
                        :min="1"
                        :disabled="userDrafts[user.user_id][field.key].mode !== 'custom'"
                        class="usage-management-limit-row__value"
                      />
                    </div>
                  </n-form-item>
                </n-gi>
              </n-grid>

              <div class="usage-management-user-card__actions">
                <n-button
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
            </n-card>
          </div>
        </n-card>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  useMessage,
} from 'naive-ui'
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
import SummaryCard from '../components/SummaryCard.vue'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatUsageResetAt } from '../utils/usageLimits'

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

const filteredUsers = computed(() => {
  const search = searchQuery.value.trim().toLowerCase()
  if (!search) {
    return users.value
  }
  return users.value.filter((user) =>
    [user.username, user.display_name || ''].join(' ').toLowerCase().includes(search)
  )
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
    { label: t('usageManagement.totalUsers'), value: String(users.value.length) },
    { label: t('usageManagement.customOverrideUsers'), value: String(customOverrideUsers) },
    { label: t('usageManagement.overLimitUsers'), value: String(overLimitUsers) },
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
  return String(limit.value)
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
.usage-management-page {
  max-width: var(--app-page-max-width);
}

.usage-management-summary-card__value {
  font-size: 20px;
}

.usage-management-card {
  border-radius: 18px;
}

.usage-management-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.usage-management-card__title {
  font-size: 16px;
  font-weight: 600;
}

.usage-management-search {
  margin-bottom: 16px;
}

.usage-management-user-grid {
  display: grid;
  gap: 16px;
}

.usage-management-user-card {
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
}

.usage-management-user-card__top {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.usage-management-user-card__name-row {
  display: grid;
  gap: 4px;
}

.usage-management-user-card__name {
  font-size: 16px;
  font-weight: 600;
}

.usage-management-user-card__meta {
  color: rgba(15, 23, 42, 0.58);
  font-size: 13px;
}

.usage-management-user-card__reset {
  display: grid;
  gap: 10px;
  text-align: right;
}

.usage-management-user-card__reset-item {
  display: grid;
  gap: 4px;
  font-size: 13px;
}

.usage-management-user-card__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin-bottom: 16px;
}

.usage-management-user-card__stat {
  padding: 12px;
  border-radius: 12px;
  background: rgba(148, 163, 184, 0.08);
}

.usage-management-user-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 6px;
}

.usage-management-user-card__stat__value {
  font-size: 18px;
  font-weight: 600;
  color: var(--n-text-color-1);
  margin-bottom: 2px;
}

.usage-management-user-card__stat-limit {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.68);
}

.usage-management-user-card__actions {
  display: flex;
  justify-content: flex-end;
  margin-top: 8px;
}

.usage-management-limit-row {
  display: flex;
  gap: 12px;
  width: 100%;
}

.usage-management-limit-row__mode {
  flex: 1;
}

.usage-management-limit-row__value {
  width: 140px;
}

@media (max-width: 767px) {
  .usage-management-user-card__top {
    flex-direction: column;
  }

  .usage-management-user-card__reset {
    text-align: left;
  }

  .usage-management-user-card__stats {
    grid-template-columns: 1fr;
  }
}
</style>
