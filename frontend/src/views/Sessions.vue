<template>
  <div class="sessions-page">
    <n-space vertical :size="16">
      <div class="sessions-page__hero">
        <div>
          <h2 class="sessions-page__title">{{ t('sessions.title') }}</h2>
          <p class="sessions-page__subtitle">
            {{ t('sessions.subtitle') }}
          </p>
        </div>
        <n-button @click="fetchSessions" :loading="loading" :disabled="loading">{{ t('sessions.reloadSessions') }}</n-button>
      </div>

      <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="sessions-summary-card" :bordered="false">
            <div class="sessions-summary-card__label">{{ item.label }}</div>
            <div class="sessions-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-alert type="info" :show-icon="false">
        {{ t('sessions.refreshTokenInfo') }}
      </n-alert>

      <n-spin :show="initialLoading" :description="t('common.loadingSessions')">
        <div v-if="hasLoadedOnce && sessions.length" class="sessions-grid">
          <n-card
            v-for="session in sessions"
            :key="session.id"
            class="sessions-card"
            :bordered="false"
            size="small"
          >
            <div class="sessions-card__header">
              <div>
                <div class="sessions-card__title-row">
                  <span class="sessions-card__title">
                    {{ session.current ? t('sessions.currentBrowserSession') : t('sessions.savedSession') }}
                  </span>
                  <n-tag size="small" round :type="tagTypeForStatus(session.status)">
                    {{ t(`status.${session.status}`) }}
                  </n-tag>
                  <n-tag v-if="session.current" size="small" round type="info">{{ t('sessions.current') }}</n-tag>
                </div>
                <div class="sessions-card__meta">
                  <span>{{ shortId(session.id) }}</span>
                  <span>{{ session.ip_address || t('sessions.ipUnavailable') }}</span>
                </div>
              </div>
              <n-button
                @click="handleRevoke(session)"
                :loading="revokingIds.includes(session.id)"
                :disabled="session.status !== 'active' || revokingIds.includes(session.id)"
              >
                {{ t('common.revoke') }}
              </n-button>
            </div>

            <div class="sessions-card__details">
              <div class="sessions-card__detail">
                <span class="sessions-card__detail-label">{{ t('sessions.created') }}</span>
                <span>{{ formatTimestamp(session.created_at) }}</span>
              </div>
              <div class="sessions-card__detail">
                <span class="sessions-card__detail-label">{{ t('sessions.lastSeen') }}</span>
                <span>{{ formatTimestamp(session.last_seen_at) }}</span>
              </div>
              <div class="sessions-card__detail">
                <span class="sessions-card__detail-label">{{ t('sessions.expires') }}</span>
                <span>{{ formatTimestamp(session.expires_at) }}</span>
              </div>
              <div class="sessions-card__detail">
                <span class="sessions-card__detail-label">{{ t('sessions.refreshSupport') }}</span>
                <span>{{ session.has_gitlab_refresh_token ? t('sessions.available') : t('sessions.unavailable') }}</span>
              </div>
            </div>

            <div class="sessions-card__tokens">
              <n-tag size="small" round :type="session.has_gitlab_access_token ? 'success' : 'warning'">
                {{ session.has_gitlab_access_token ? t('sessions.accessTokenStored') : t('sessions.accessTokenMissing') }}
              </n-tag>
              <n-tag size="small" round :type="session.has_gitlab_refresh_token ? 'success' : 'default'">
                {{ session.has_gitlab_refresh_token ? t('sessions.refreshTokenStored') : t('sessions.refreshTokenMissing') }}
              </n-tag>
            </div>

            <p v-if="session.user_agent" class="sessions-card__agent">{{ session.user_agent }}</p>
          </n-card>
        </div>

        <n-empty v-else-if="hasLoadedOnce" :description="t('sessions.noSessions')" />
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
  NEmpty,
  NGi,
  NGrid,
  NSpace,
  NSpin,
  NTag,
  useMessage
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { getSessions, revokeSession, type SessionInfo } from '../api'
import { initializeAuth, logoutAndClearAuth } from '../auth'
import { formatDateTimeLocal } from '../utils/datetime'

const message = useMessage()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const hasLoadedOnce = ref(false)
const sessions = ref<SessionInfo[]>([])
const revokingIds = ref<string[]>([])
const initialLoading = computed(() => loading.value && !hasLoadedOnce.value)

const summaryItems = computed(() => {
  const active = sessions.value.filter((session) => session.status === 'active').length
  const refreshCapable = sessions.value.filter((session) => session.has_gitlab_refresh_token).length
  const current = sessions.value.find((session) => session.current)
  return [
    { label: t('sessions.knownSessions'), value: String(sessions.value.length) },
    { label: t('sessions.activeSessions'), value: String(active) },
    { label: t('sessions.refreshCapable'), value: String(refreshCapable) },
    { label: t('sessions.currentSession'), value: current ? shortId(current.id) : '—' }
  ]
})

function shortId(value: string) {
  return value.length > 12 ? `${value.slice(0, 8)}…${value.slice(-4)}` : value
}

function formatTimestamp(value: string | null) {
  if (!value) {
    return '—'
  }
  return formatDateTimeLocal(value)
}

function tagTypeForStatus(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'active') {
    return 'success'
  }
  if (status === 'expired') {
    return 'warning'
  }
  if (status === 'revoked') {
    return 'error'
  }
  return 'default'
}

async function fetchSessions() {
  loading.value = true
  try {
    sessions.value = await getSessions()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('sessions.failedToFetchSessions'))
  } finally {
    hasLoadedOnce.value = true
    loading.value = false
  }
}

async function handleRevoke(session: SessionInfo) {
  revokingIds.value = Array.from(new Set([...revokingIds.value, session.id]))
  try {
    const result = await revokeSession(session.id)
    if (result.current_session_revoked) {
      message.success(t('sessions.currentSessionRevoked'))
      await logoutAndClearAuth()
      return
    }

    message.success(t('sessions.sessionRevoked'))
    await fetchSessions()
    await initializeAuth(true)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('sessions.failedToRevokeSession'))
  } finally {
    revokingIds.value = revokingIds.value.filter((id) => id !== session.id)
  }
}

onMounted(() => {
  fetchSessions()
})
</script>

<style scoped>
.sessions-page {
  max-width: 1240px;
}

.sessions-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.sessions-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.sessions-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.sessions-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.sessions-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.sessions-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.sessions-grid {
  display: grid;
  gap: 16px;
}

.sessions-card {
  border-radius: 16px;
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.96), rgba(248, 250, 252, 0.9));
}

.sessions-card__header {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 16px;
}

.sessions-card__title-row {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.sessions-card__title {
  font-size: 16px;
  font-weight: 600;
}

.sessions-card__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 12px;
  color: rgba(15, 23, 42, 0.58);
  font-size: 13px;
}

.sessions-card__details {
  display: grid;
  grid-template-columns: repeat(2, minmax(180px, 1fr));
  gap: 12px 20px;
  margin-bottom: 12px;
}

.sessions-card__detail {
  display: grid;
  gap: 4px;
  color: rgba(15, 23, 42, 0.68);
  font-size: 13px;
}

.sessions-card__detail-label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

.sessions-card__tokens {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.sessions-card__agent {
  margin: 12px 0 0;
  color: rgba(15, 23, 42, 0.56);
  font-size: 13px;
  line-height: 1.5;
  word-break: break-word;
}

@media (max-width: 767px) {
  .sessions-page__hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .sessions-page__title {
    font-size: 24px;
  }

  .sessions-page__subtitle {
    max-width: none;
  }

  .sessions-card__header {
    flex-direction: column;
  }

  .sessions-card__details {
    grid-template-columns: 1fr;
  }
}
</style>
