<template>
  <div class="access-page">
    <n-space vertical :size="16">
      <div class="access-page__hero">
        <div>
          <h2 class="access-page__title">{{ t('accessManagement.title') }}</h2>
          <p class="access-page__subtitle">
            {{ t('accessManagement.subtitle') }}
          </p>
        </div>
        <n-button @click="fetchUsers" :loading="usersLoading" :disabled="usersLoading">
          {{ t('accessManagement.reloadUsers') }}
        </n-button>
      </div>

      <n-alert type="info" :show-icon="false" class="user-management__intro">
        {{ t('accessManagement.intro') }}
      </n-alert>

      <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 1 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="access-summary-card" :bordered="false">
            <div class="access-summary-card__label">{{ item.label }}</div>
            <div class="access-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-card class="access-card" :bordered="false">
        <div class="user-management__toolbar">
          <n-space :size="12" wrap>
            <n-input
              v-model:value="userSearch"
               :placeholder="t('accessManagement.searchPlaceholder')"
              clearable
              class="user-management__search"
            />
            <n-select
              v-model:value="roleFilter"
              :options="roleFilterOptions"
              clearable
               :placeholder="t('accessManagement.filterByRole')"
              class="user-management__filter"
            />
            <n-select
              v-model:value="stateFilter"
              :options="stateFilterOptions"
              clearable
               :placeholder="t('accessManagement.filterByState')"
              class="user-management__filter"
            />
          </n-space>
        </div>

         <n-spin :show="initialLoading" :description="t('accessManagement.loading')">
          <div v-if="hasLoadedOnce && filteredUsers.length" class="user-management__grid">
            <n-card
              v-for="user in filteredUsers"
              :key="user.id"
              size="small"
              class="user-management__card"
              :bordered="false"
            >
              <div class="user-management__card-top">
                <div class="user-management__identity">
                  <n-avatar round :src="user.avatar_url || undefined">
                    {{ userAvatarFallback(user) }}
                  </n-avatar>
                  <div>
                    <div class="user-management__name-row">
                      <span class="user-management__name">
                        {{ user.display_name || user.username }}
                      </span>
                      <n-tag size="small" round :type="user.state === 'active' ? 'success' : 'error'">
                         {{ t(`status.${user.state}`) }}
                      </n-tag>
                      <n-tag size="small" round :type="user.platform_role === 'platform_admin' ? 'warning' : 'default'">
                         {{ user.platform_role === 'platform_admin' ? t('accessManagement.platformAdmin') : t('accessManagement.platformUser') }}
                      </n-tag>
                      <n-tag size="small" round>
                        {{ roleSourceLabel(user.platform_role_source) }}
                      </n-tag>
                       <n-tag v-if="user.is_current_user" size="small" round type="info">{{ t('accessManagement.currentUser') }}</n-tag>
                    </div>
                    <div class="user-management__meta">
                      <span>@{{ user.username }}</span>
                      <span v-if="user.email">{{ user.email }}</span>
                      <span>ID {{ user.gitlab_user_id }}</span>
                    </div>
                  </div>
                </div>
                <div class="user-management__stats">
                  <div>
                     <div class="user-management__stat-label">{{ t('accessManagement.activeSessions') }}</div>
                    <div class="user-management__stat-value">{{ user.active_session_count }}</div>
                  </div>
                  <div>
                     <div class="user-management__stat-label">{{ t('accessManagement.lastSeen') }}</div>
                    <div class="user-management__stat-value">
                      {{ formatTimestamp(user.last_session_seen_at || user.last_login_at) }}
                    </div>
                  </div>
                </div>
              </div>

              <div class="user-management__details">
                <div class="user-management__detail">
                   <span class="user-management__detail-label">{{ t('common.created') }}</span>
                  <span>{{ formatTimestamp(user.created_at) }}</span>
                </div>
                <div class="user-management__detail">
                   <span class="user-management__detail-label">{{ t('accessManagement.lastLogin') }}</span>
                  <span>{{ formatTimestamp(user.last_login_at) }}</span>
                </div>
              </div>

              <n-grid :cols="isMobile ? 1 : 2" :x-gap="12" :y-gap="8">
                <n-gi>
                   <n-form-item :label="t('accessManagement.role')" class="user-management__field">
                    <n-select
                      v-model:value="userDrafts[user.id].platform_role"
                      :options="roleOptions"
                      :disabled="user.is_current_user || isUserSaving(user.id)"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                   <n-form-item :label="t('accessManagement.state')" class="user-management__field">
                    <n-select
                      v-model:value="userDrafts[user.id].state"
                      :options="stateOptions"
                      :disabled="user.is_current_user || isUserSaving(user.id)"
                    />
                  </n-form-item>
                </n-gi>
              </n-grid>

              <div class="user-management__actions">
                <n-button
                  type="primary"
                  secondary
                  @click="handleSaveUser(user)"
                  :loading="isUserSaving(user.id)"
                  :disabled="user.is_current_user || !isUserDirty(user)"
                >
                   {{ t('accessManagement.saveAccess') }}
                </n-button>
                <n-button
                  @click="handleRevokeUserSessions(user)"
                  :loading="isUserRevoking(user.id)"
                  :disabled="user.is_current_user || isUserRevoking(user.id)"
                >
                   {{ t('accessManagement.revokeSessions') }}
                </n-button>
              </div>

              <p v-if="user.is_current_user" class="user-management__hint">
                 {{ t('accessManagement.selfReadonly') }}
              </p>
            </n-card>
          </div>

           <n-empty v-else-if="hasLoadedOnce" :description="t('accessManagement.noUsers')" />
        </n-spin>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import {
  NAlert,
  NAvatar,
  NButton,
  NCard,
  NEmpty,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NTag,
  useMessage
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import {
  getAdminUsers,
  revokeAdminUserSessions,
  updateAdminUser,
  type AdminUser
} from '../api'
import { formatDateTimeLocal } from '../utils/datetime'

type AdminUserDraft = {
  platform_role: string
  state: string
}

const message = useMessage()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const usersLoading = ref(false)
const hasLoadedOnce = ref(false)
const users = ref<AdminUser[]>([])
const userDrafts = ref<Record<number, AdminUserDraft>>({})
const userSearch = ref('')
const roleFilter = ref<string | null>(null)
const stateFilter = ref<string | null>(null)
const savingUserIds = ref<number[]>([])
const revokingUserIds = ref<number[]>([])
const initialLoading = computed(() => usersLoading.value && !hasLoadedOnce.value)

const roleOptions = computed(() => [
  { label: t('accessManagement.platformAdmin'), value: 'platform_admin' },
  { label: t('accessManagement.platformUser'), value: 'platform_user' }
])

const stateOptions = computed(() => [
  { label: t('status.active'), value: 'active' },
  { label: t('status.disabled'), value: 'disabled' }
])

const roleFilterOptions = computed(() => [
  { label: t('accessManagement.platformAdmin'), value: 'platform_admin' },
  { label: t('accessManagement.platformUser'), value: 'platform_user' }
])

const stateFilterOptions = computed(() => [
  { label: t('status.active'), value: 'active' },
  { label: t('status.disabled'), value: 'disabled' }
])

const summaryItems = computed(() => {
  const adminUsers = users.value.filter((user) => user.platform_role === 'platform_admin').length
  const disabledUsers = users.value.filter((user) => user.state === 'disabled').length
  const activeSessions = users.value.reduce((total, user) => total + user.active_session_count, 0)
  return [
    { label: t('accessManagement.knownUsers'), value: String(users.value.length) },
    { label: t('accessManagement.platformAdmins'), value: String(adminUsers) },
    { label: t('accessManagement.disabledUsers'), value: String(disabledUsers) },
    { label: t('accessManagement.activeSessions'), value: String(activeSessions) }
  ]
})

const filteredUsers = computed(() => {
  const search = userSearch.value.trim().toLowerCase()
  return users.value.filter((user) => {
    if (roleFilter.value && user.platform_role !== roleFilter.value) {
      return false
    }
    if (stateFilter.value && user.state !== stateFilter.value) {
      return false
    }
    if (!search) {
      return true
    }
    return [user.username, user.display_name || '', user.email || '']
      .join(' ')
      .toLowerCase()
      .includes(search)
  })
})

function syncUserDrafts(items: AdminUser[]) {
  userDrafts.value = Object.fromEntries(
    items.map((user) => [
      user.id,
      {
        platform_role: user.platform_role,
        state: user.state
      }
    ])
  )
}

function userAvatarFallback(user: AdminUser) {
  return (user.display_name || user.username).slice(0, 1).toUpperCase()
}

function roleSourceLabel(source: string) {
  if (source === 'manual') {
    return t('accessManagement.manualOverride')
  }
  if (source === 'break_glass') {
    return t('accessManagement.breakGlass')
  }
  return t('accessManagement.bootstrap')
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return '—'
  }
  return formatDateTimeLocal(value)
}

function isUserSaving(userId: number) {
  return savingUserIds.value.includes(userId)
}

function isUserRevoking(userId: number) {
  return revokingUserIds.value.includes(userId)
}

function isUserDirty(user: AdminUser) {
  const draft = userDrafts.value[user.id]
  if (!draft) {
    return false
  }
  return draft.platform_role !== user.platform_role || draft.state !== user.state
}

function setSavingUser(userId: number, active: boolean) {
  savingUserIds.value = active
    ? Array.from(new Set([...savingUserIds.value, userId]))
    : savingUserIds.value.filter((id) => id !== userId)
}

function setRevokingUser(userId: number, active: boolean) {
  revokingUserIds.value = active
    ? Array.from(new Set([...revokingUserIds.value, userId]))
    : revokingUserIds.value.filter((id) => id !== userId)
}

function replaceUser(updatedUser: AdminUser) {
  users.value = users.value.map((user) => (user.id === updatedUser.id ? updatedUser : user))
  userDrafts.value = {
    ...userDrafts.value,
    [updatedUser.id]: {
      platform_role: updatedUser.platform_role,
      state: updatedUser.state
    }
  }
}

async function fetchUsers() {
  usersLoading.value = true
  try {
    const result = await getAdminUsers()
    users.value = result
    syncUserDrafts(result)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('accessManagement.failedToFetchUsers'))
  } finally {
    hasLoadedOnce.value = true
    usersLoading.value = false
  }
}

async function handleSaveUser(user: AdminUser) {
  const draft = userDrafts.value[user.id]
  if (!draft) {
    return
  }

  const payload: Record<string, string> = {}
  if (draft.platform_role !== user.platform_role) {
    payload.platform_role = draft.platform_role
  }
  if (draft.state !== user.state) {
    payload.state = draft.state
  }
  if (!Object.keys(payload).length) {
    return
  }

  setSavingUser(user.id, true)
  try {
    const updatedUser = await updateAdminUser(user.id, payload)
    replaceUser(updatedUser)
    message.success(t('accessManagement.updatedAccess', { username: updatedUser.username }))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('accessManagement.failedToUpdateUser'))
  } finally {
    setSavingUser(user.id, false)
  }
}

async function handleRevokeUserSessions(user: AdminUser) {
  setRevokingUser(user.id, true)
  try {
    const result = await revokeAdminUserSessions(user.id)
    await fetchUsers()
    message.success(
      result.revoked_count > 0
        ? t('accessManagement.revokedSessions', { count: result.revoked_count, username: user.username })
        : t('accessManagement.noActiveSessions', { username: user.username })
    )
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('accessManagement.failedToRevokeSessions'))
  } finally {
    setRevokingUser(user.id, false)
  }
}

onMounted(() => {
  fetchUsers()
})
</script>

<style scoped>
.access-page {
  max-width: 1240px;
}

.access-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.access-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.access-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.access-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.access-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.access-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.access-card {
  border-radius: 18px;
}

.user-management__intro {
  margin-bottom: 0;
}

.user-management__toolbar {
  width: 100%;
  margin-bottom: 16px;
}

.user-management__search {
  min-width: 260px;
  flex: 1;
}

.user-management__filter {
  min-width: 180px;
}

.user-management__grid {
  display: grid;
  gap: 16px;
}

.user-management__card {
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
}

.user-management__card-top {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.user-management__identity {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.user-management__name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 6px;
}

.user-management__name {
  font-size: 16px;
  font-weight: 600;
}

.user-management__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  color: rgba(15, 23, 42, 0.58);
  font-size: 13px;
}

.user-management__stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(120px, 1fr));
  gap: 12px;
  min-width: 280px;
}

.user-management__stat-label,
.user-management__detail-label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.user-management__stat-value {
  margin-top: 4px;
  font-size: 14px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.user-management__details {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 20px;
  margin-bottom: 12px;
  color: rgba(15, 23, 42, 0.68);
  font-size: 13px;
}

.user-management__detail {
  display: grid;
  gap: 4px;
}

.user-management__field :deep(.n-form-item-feedback-wrapper) {
  display: none;
}

.user-management__actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.user-management__hint {
  margin: 12px 0 0;
  color: rgba(15, 23, 42, 0.56);
  font-size: 13px;
}

@media (max-width: 767px) {
  .access-page__hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .access-page__title {
    font-size: 24px;
  }

  .access-page__subtitle {
    max-width: none;
  }

  .user-management__card-top {
    flex-direction: column;
  }

  .user-management__stats {
    min-width: 0;
    grid-template-columns: 1fr 1fr;
  }
}
</style>
