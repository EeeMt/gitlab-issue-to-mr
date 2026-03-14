<template>
  <div class="diagnostics-page">
    <n-space vertical :size="16">
      <div class="diagnostics-page__hero">
        <div>
          <h2 class="diagnostics-page__title">OIDC Diagnostics</h2>
          <p class="diagnostics-page__subtitle">
            Inspect issuer discovery, endpoint metadata, cookie policy, required scopes, and the
            current auth mode from one admin-only page.
          </p>
        </div>
        <n-button @click="fetchDiagnostics" :loading="loading" :disabled="loading">
          Refresh diagnostics
        </n-button>
      </div>

      <n-grid v-if="diagnostics" :cols="isMobile ? 1 : 4" :x-gap="16" :y-gap="16">
        <n-gi v-for="item in summaryItems" :key="item.label">
          <n-card size="small" class="diagnostics-summary-card" :bordered="false">
            <div class="diagnostics-summary-card__label">{{ item.label }}</div>
            <div class="diagnostics-summary-card__value">{{ item.value }}</div>
          </n-card>
        </n-gi>
      </n-grid>

      <n-spin :show="loading">
        <n-space v-if="diagnostics" vertical :size="16">
          <n-alert v-if="diagnostics.warnings.length" type="warning" :show-icon="false">
            <div class="diagnostics-alert__title">Operator warnings</div>
            <ul class="diagnostics-alert__list">
              <li v-for="warning in diagnostics.warnings" :key="warning">{{ warning }}</li>
            </ul>
          </n-alert>

          <n-card class="diagnostics-card" :bordered="false">
            <template #header>
              <div class="diagnostics-card__header">
                <div>
                  <div class="diagnostics-card__title">Checks</div>
                  <div class="diagnostics-card__subtitle">Live diagnostics against effective runtime config</div>
                </div>
              </div>
            </template>

            <div class="diagnostics-checks">
              <div
                v-for="check in diagnostics.checks"
                :key="check.key"
                class="diagnostics-check"
                :class="`diagnostics-check--${check.status}`"
              >
                <div class="diagnostics-check__top">
                  <span class="diagnostics-check__label">{{ check.label }}</span>
                  <n-tag size="small" round :type="tagType(check.status)">
                    {{ check.status }}
                  </n-tag>
                </div>
                <div class="diagnostics-check__detail">{{ check.detail }}</div>
              </div>
            </div>
          </n-card>

          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
            <n-gi>
              <n-card class="diagnostics-card" :bordered="false">
                <template #header>
                  <div class="diagnostics-card__header">
                    <div>
                      <div class="diagnostics-card__title">Auth mode summary</div>
                      <div class="diagnostics-card__subtitle">Current effective settings and safety posture</div>
                    </div>
                  </div>
                </template>

                <div class="diagnostics-detail-list">
                  <div class="diagnostics-detail-list__item">
                    <span>OIDC login</span>
                    <strong>{{ diagnostics.oidc_enabled ? 'Enabled' : 'Disabled' }}</strong>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Break-glass</span>
                    <strong>{{ diagnostics.break_glass_enabled ? 'Enabled' : 'Disabled' }}</strong>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Client ID</span>
                    <strong>{{ diagnostics.client_id_configured ? 'Configured' : 'Missing' }}</strong>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Client secret</span>
                    <strong>{{ diagnostics.client_secret_configured ? 'Configured' : 'Missing' }}</strong>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Cookie policy</span>
                    <strong>{{ diagnostics.cookie_secure ? 'Secure' : 'Insecure' }} / {{ diagnostics.cookie_samesite }}</strong>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Session TTL</span>
                    <strong>{{ diagnostics.session_ttl_seconds }}s</strong>
                  </div>
                </div>
              </n-card>
            </n-gi>

            <n-gi>
              <n-card class="diagnostics-card" :bordered="false">
                <template #header>
                  <div class="diagnostics-card__header">
                    <div>
                      <div class="diagnostics-card__title">Provider metadata</div>
                      <div class="diagnostics-card__subtitle">Discovery and endpoint values currently in use</div>
                    </div>
                  </div>
                </template>

                <div class="diagnostics-detail-list">
                  <div class="diagnostics-detail-list__item">
                    <span>Issuer URL</span>
                    <code>{{ diagnostics.issuer_url || '—' }}</code>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Discovery issuer</span>
                    <code>{{ diagnostics.discovery_issuer || '—' }}</code>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Redirect URI</span>
                    <code>{{ diagnostics.redirect_uri || '—' }}</code>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Authorization endpoint</span>
                    <code>{{ diagnostics.authorization_endpoint || '—' }}</code>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Token endpoint</span>
                    <code>{{ diagnostics.token_endpoint || '—' }}</code>
                  </div>
                  <div class="diagnostics-detail-list__item">
                    <span>Userinfo endpoint</span>
                    <code>{{ diagnostics.userinfo_endpoint || '—' }}</code>
                  </div>
                </div>
              </n-card>
            </n-gi>
          </n-grid>

          <n-card class="diagnostics-card" :bordered="false">
            <template #header>
              <div class="diagnostics-card__header">
                <div>
                  <div class="diagnostics-card__title">Required scopes</div>
                  <div class="diagnostics-card__subtitle">Scopes the GitLab OAuth application should allow</div>
                </div>
              </div>
            </template>

            <n-space :size="8" wrap>
              <n-tag v-for="scope in diagnostics.required_scopes" :key="scope" round>{{ scope }}</n-tag>
            </n-space>

            <div class="diagnostics-scope-string">
              <span class="diagnostics-scope-string__label">Authorization scope string</span>
              <code>{{ diagnostics.required_scope_string }}</code>
            </div>

            <div v-if="diagnostics.authorization_url_preview" class="diagnostics-scope-string">
              <span class="diagnostics-scope-string__label">Authorization URL preview</span>
              <code>{{ diagnostics.authorization_url_preview }}</code>
            </div>
          </n-card>
        </n-space>
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
  NGi,
  NGrid,
  NSpace,
  NSpin,
  NTag,
  useMessage
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { getOidcDiagnostics, type OidcDiagnosticsResult } from '../api'

const message = useMessage()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

const loading = ref(false)
const diagnostics = ref<OidcDiagnosticsResult | null>(null)

const summaryItems = computed(() => {
  if (!diagnostics.value) {
    return []
  }
  const okCount = diagnostics.value.checks.filter((check) => check.status === 'ok').length
  const warningCount = diagnostics.value.checks.filter((check) => check.status === 'warning').length
  const errorCount = diagnostics.value.checks.filter((check) => check.status === 'error').length
  return [
    { label: 'OIDC Login', value: diagnostics.value.oidc_enabled ? 'Enabled' : 'Disabled' },
    { label: 'Healthy Checks', value: String(okCount) },
    { label: 'Warnings', value: String(warningCount) },
    { label: 'Errors', value: String(errorCount) }
  ]
})

function tagType(status: string): 'success' | 'warning' | 'error' | 'default' {
  if (status === 'ok') {
    return 'success'
  }
  if (status === 'warning') {
    return 'warning'
  }
  if (status === 'error') {
    return 'error'
  }
  return 'default'
}

async function fetchDiagnostics() {
  loading.value = true
  try {
    diagnostics.value = await getOidcDiagnostics()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to fetch OIDC diagnostics')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  fetchDiagnostics()
})
</script>

<style scoped>
.diagnostics-page {
  max-width: 1240px;
  padding: 8px 0;
}

.diagnostics-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.diagnostics-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.diagnostics-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.diagnostics-summary-card {
  background: linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02));
  border-radius: 12px;
}

.diagnostics-summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  margin-bottom: 8px;
}

.diagnostics-summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.diagnostics-alert__title {
  font-weight: 600;
  margin-bottom: 8px;
}

.diagnostics-alert__list {
  margin: 0;
  padding-left: 18px;
}

.diagnostics-card {
  border-radius: 18px;
}

.diagnostics-card__title {
  font-size: 18px;
  font-weight: 600;
}

.diagnostics-card__subtitle {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
  margin-top: 4px;
}

.diagnostics-checks {
  display: grid;
  gap: 12px;
}

.diagnostics-check {
  border-radius: 14px;
  padding: 14px 16px;
  border: 1px solid rgba(15, 23, 42, 0.08);
}

.diagnostics-check--ok {
  background: rgba(24, 160, 88, 0.06);
}

.diagnostics-check--warning {
  background: rgba(240, 160, 32, 0.08);
}

.diagnostics-check--error {
  background: rgba(208, 48, 80, 0.08);
}

.diagnostics-check__top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.diagnostics-check__label {
  font-weight: 600;
}

.diagnostics-check__detail,
.diagnostics-detail-list__item,
.diagnostics-scope-string {
  color: rgba(15, 23, 42, 0.72);
  line-height: 1.6;
}

.diagnostics-detail-list {
  display: grid;
  gap: 12px;
}

.diagnostics-detail-list__item {
  display: grid;
  gap: 4px;
}

.diagnostics-detail-list__item code,
.diagnostics-scope-string code {
  word-break: break-all;
}

.diagnostics-scope-string {
  margin-top: 16px;
  display: grid;
  gap: 6px;
}

.diagnostics-scope-string__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.56);
  text-transform: uppercase;
  letter-spacing: 0.03em;
}

@media (max-width: 767px) {
  .diagnostics-page__hero {
    flex-direction: column;
    align-items: flex-start;
  }

  .diagnostics-page__title {
    font-size: 24px;
  }

  .diagnostics-page__subtitle {
    max-width: none;
  }

  .diagnostics-check__top {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
