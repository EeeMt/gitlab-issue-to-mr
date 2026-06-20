<template>
  <aside class="issue-overview" data-testid="issue-metadata-card">
    <n-card class="overview-card overview-card--delivery" :bordered="false">
      <template #header>
        <div class="overview-card__header">
          <div>
            <div class="overview-card__eyebrow">{{ t('issue.deliveryOverview') }}</div>
            <div class="overview-card__title">{{ t('issue.deliveryStatus') }}</div>
          </div>
          <n-tag size="small" round :type="issue.merge_request_url ? 'success' : 'default'">
            {{ issue.merge_request_url ? t('issue.deliveryReady') : t('issue.deliveryPending') }}
          </n-tag>
        </div>
      </template>

      <div class="delivery-stack">
        <div class="delivery-row">
          <span class="delivery-row__label">
            <n-icon size="15"><GitPullRequest /></n-icon>
            {{ t('issue.field.mergeRequest') }}
          </span>
          <a
            v-if="issue.merge_request_url"
            :href="issue.merge_request_url"
            target="_blank"
            rel="noopener noreferrer"
            class="overview-link"
          >
            !{{ issue.merge_request_iid }} ↗
          </a>
          <span v-else class="overview-muted">{{ t('issue.noMergeRequest') }}</span>
        </div>

        <div class="branch-journey">
          <template v-for="(branch, index) in branches" :key="`${branch.kind}-${branch.name}`">
            <span v-if="index" class="branch-journey__line" aria-hidden="true"></span>
            <n-tooltip
              trigger="hover"
              placement="top"
              :content-style="issueDetailTooltipContentStyle"
              :theme-overrides="issueDetailTooltipThemeOverrides"
            >
              <template #trigger>
                <component
                  :is="branchUrl(branch.name) ? 'a' : 'div'"
                  :href="branchUrl(branch.name) || undefined"
                  :target="branchUrl(branch.name) ? '_blank' : undefined"
                  :rel="branchUrl(branch.name) ? 'noopener noreferrer' : undefined"
                  class="branch-node"
                  :class="[`branch-node--${branch.kind}`, { 'overview-link': branchUrl(branch.name) }]"
                >
                  <span>{{ branch.label }}</span>
                  <code>{{ branch.name }}</code>
                </component>
              </template>
              <code class="branch-tooltip__value">{{ branch.name }}</code>
            </n-tooltip>
          </template>
          <span v-if="branches.length === 0" class="overview-muted">—</span>
        </div>
      </div>

      <div class="overview-stats">
        <div class="overview-stat">
          <span>{{ t('issue.taskCountShort') }}</span>
          <strong>{{ issue.tasks?.length ?? issue.task_count ?? 0 }}</strong>
        </div>
        <div class="overview-stat">
          <span>{{ t('common.changes') }}</span>
          <strong>{{ formatNumber(issue.totals?.total_changes) }}</strong>
          <small v-if="issue.totals?.total_changes">
            <b class="stat-add">+{{ issue.totals.additions }}</b>
            <b class="stat-del">-{{ issue.totals.deletions }}</b>
          </small>
        </div>
        <div class="overview-stat">
          <span>{{ t('issue.totalTaskDuration') }}</span>
          <strong>{{ issue.totals ? formatDurationSec(issue.totals.duration_seconds) : '—' }}</strong>
        </div>
        <div class="overview-stat">
          <span>{{ t('analytics.tokens') }}</span>
          <strong>{{ tokenTotal }}</strong>
        </div>
      </div>
    </n-card>

    <n-card class="overview-card" :bordered="false">
      <template #header>
        <div class="overview-card__title">{{ t('issue.basicInfo') }}</div>
      </template>

      <div class="overview-metadata">
        <div class="overview-metadata__row">
          <span><n-icon size="14"><FolderOpenOutline /></n-icon>{{ t('issue.field.project') }}</span>
          <a v-if="projectUrl" :href="projectUrl" target="_blank" rel="noopener noreferrer" class="overview-link">
            {{ projectName }}
          </a>
          <strong v-else>{{ projectName }}</strong>
        </div>
        <div class="overview-metadata__row">
          <span><n-icon size="14"><PersonOutline /></n-icon>{{ t('issue.field.creator') }}</span>
          <strong>{{ issue.initiator_username || '—' }}</strong>
        </div>
        <div class="overview-metadata__row">
          <span><n-icon size="14"><CodeOutline /></n-icon>{{ t('issue.field.sessionId') }}</span>
          <n-tooltip
            v-if="issue.claude_session_id"
            trigger="hover"
            placement="left"
            :content-style="issueDetailTooltipContentStyle"
            :theme-overrides="issueDetailTooltipThemeOverrides"
          >
            <template #trigger>
              <code
                class="overview-code overview-code--session"
                data-testid="issue-session-id-trigger"
                tabindex="0"
              >{{ abbreviatedSessionId }}</code>
            </template>
            <code class="session-id-tooltip__value">{{ issue.claude_session_id }}</code>
          </n-tooltip>
          <strong v-else class="metadata-muted">—</strong>
        </div>
        <div v-if="issue.branch_name || issue.branch_deleted" class="overview-metadata__row" data-testid="issue-branch-policy-row">
          <span><n-icon size="14"><GitBranchOutline /></n-icon>{{ t('issue.deleteBranchOnClose') }}</span>
          <div class="overview-metadata__tags">
            <n-tag size="tiny" round :data-testid="issue.delete_branch_on_close ? 'delete-branch-badge' : 'keep-branch-badge'">
              {{ issue.delete_branch_on_close ? t('issue.deleteBranchBadge') : t('issue.keepBranchBadge') }}
            </n-tag>
            <n-tag v-if="issue.branch_deleted" size="tiny" round data-testid="branch-deleted-badge">
              {{ t('issue.branchDeletedBadge') }}
            </n-tag>
          </div>
        </div>
        <div v-if="issue.status === 'closed' && issue.closed_via" class="overview-metadata__row">
          <span><n-icon size="14"><InformationCircleOutline /></n-icon>{{ t('issue.closedViaLabel') }}</span>
          <strong>{{ issue.closed_via === 'webhook_mr_merged' ? t('issue.closedViaWebhookMrMerged') : t('issue.closedViaManual') }}</strong>
        </div>
        <div class="overview-metadata__row">
          <span><n-icon size="14"><TimeOutline /></n-icon>{{ t('common.created') }}</span>
          <strong>{{ formatCompactDateTime(issue.created_at) }}</strong>
        </div>
        <div class="overview-metadata__row">
          <span><n-icon size="14"><TimeOutline /></n-icon>{{ t('issue.field.updatedAt') }}</span>
          <strong>{{ formatCompactDateTime(issue.updated_at) }}</strong>
        </div>
      </div>
    </n-card>
  </aside>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NIcon, NTag, NTooltip } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  CodeOutline,
  FolderOpenOutline,
  GitBranchOutline,
  GitPullRequest,
  InformationCircleOutline,
  PersonOutline,
  TimeOutline,
} from '@vicons/ionicons5'
import type { Issue } from '../../api'
import { formatDateTimeUtc8Compact } from '../../utils/datetime'
import { formatDurationSec } from '../../utils/format'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './tooltip'

const props = defineProps<{
  issue: Issue
  projectName: string
  projectUrl: string | null
}>()

const { t } = useI18n()

const branches = computed(() => [
  props.issue.base_branch ? { kind: 'base', label: t('issue.field.baseBranch'), name: props.issue.base_branch } : null,
  props.issue.branch_name ? { kind: 'work', label: t('createTask.branchFlowWorkBranch'), name: props.issue.branch_name } : null,
  props.issue.target_branch ? { kind: 'target', label: t('issue.field.targetBranch'), name: props.issue.target_branch } : null,
].filter((branch): branch is { kind: string; label: string; name: string } => branch !== null))

const tokenTotal = computed(() => {
  const totals = props.issue.totals
  if (!totals) return '—'
  return formatNumber(totals.input_tokens + totals.output_tokens)
})

const abbreviatedSessionId = computed(() => {
  const sessionId = props.issue.claude_session_id ?? ''
  if (sessionId.length <= 18) return sessionId
  return `${sessionId.slice(0, 8)}…${sessionId.slice(-6)}`
})

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return '—'
  return Math.round(value).toLocaleString()
}

function formatCompactDateTime(value?: string | null): string {
  return value ? formatDateTimeUtc8Compact(value) : '—'
}

function branchUrl(branchName: string): string | null {
  if (!props.projectUrl) return null
  return `${props.projectUrl}/-/tree/${branchName.split('/').map(encodeURIComponent).join('/')}`
}
</script>

<style scoped>
.issue-overview {
  display: grid;
  gap: 16px;
}

.overview-card {
  border: 1px solid rgba(15, 23, 42, 0.075);
  border-radius: var(--app-card-radius);
  box-shadow: 0 10px 30px rgba(15, 23, 42, 0.045);
}

.overview-card--delivery {
  background: linear-gradient(160deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.98));
}

.overview-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.overview-card__eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.overview-card__title {
  color: var(--n-text-color-1);
  font-size: 17px;
  font-weight: 650;
}

.delivery-stack {
  display: grid;
  gap: 14px;
}

.delivery-row,
.overview-metadata__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.delivery-row__label,
.overview-metadata__row > span {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  color: var(--n-text-color-3);
  font-size: 12px;
  white-space: nowrap;
}

.overview-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}

.overview-link:hover {
  text-decoration: underline;
}

.overview-muted,
.metadata-muted {
  color: var(--n-text-color-3);
}

.branch-journey {
  display: flex;
  align-items: center;
  gap: 4px;
}

.branch-journey__line {
  flex: 0 0 14px;
  height: 1px;
  background: rgba(100, 116, 139, 0.32);
}

.branch-node {
  display: grid;
  flex: 1 1 0;
  gap: 3px;
  min-width: 0;
  padding: 8px;
  border: 1px solid rgba(100, 116, 139, 0.14);
  border-radius: 7px;
  background: rgba(255, 255, 255, 0.76);
  color: inherit;
  text-decoration: none;
}

.branch-node span {
  color: var(--n-text-color-3);
  font-size: 10px;
}

.branch-node code {
  overflow: hidden;
  font-family: var(--n-font-family-mono, 'SF Mono', monospace);
  font-size: 11px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.branch-node--work {
  border-color: rgba(5, 150, 105, 0.22);
  background: rgba(5, 150, 105, 0.055);
}

.overview-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 16px;
}

.overview-stat {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 9px 10px;
  border-radius: 7px;
  background: rgba(15, 23, 42, 0.035);
}

.overview-stat span {
  color: var(--n-text-color-3);
  font-size: 11px;
}

.overview-stat strong {
  overflow: hidden;
  color: rgba(15, 23, 42, 0.86);
  font-size: 17px;
  font-weight: 650;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.overview-stat small {
  display: flex;
  gap: 6px;
  font-size: 10px;
}

.overview-stat small b {
  font-weight: 600;
}

.stat-add { color: #15803d; }
.stat-del { color: #be123c; }

.overview-metadata {
  display: grid;
  gap: 13px;
}

.overview-metadata__row {
  align-items: flex-start;
}

.overview-metadata__row > strong,
.overview-metadata__row > a,
.overview-metadata__row > code,
.overview-metadata__tags {
  min-width: 0;
  max-width: 64%;
  overflow: hidden;
  color: var(--n-text-color-2);
  font-size: 12px;
  font-weight: 500;
  text-align: right;
  text-overflow: ellipsis;
}

.overview-metadata__row > strong,
.overview-metadata__row > a,
.overview-metadata__row > code {
  white-space: nowrap;
}

.overview-code {
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(15, 23, 42, 0.055);
  font-family: var(--n-font-family-mono, 'SF Mono', monospace);
}

.overview-code--session {
  display: inline-block;
  max-width: 132px;
  overflow: hidden;
  cursor: help;
  text-overflow: ellipsis;
  vertical-align: middle;
  white-space: nowrap;
}

.branch-tooltip__value,
.session-id-tooltip__value {
  display: block;
  max-width: min(420px, 72vw);
  overflow-wrap: anywhere;
  font-family: var(--n-font-family-mono, 'SF Mono', monospace);
  font-size: 12px;
}

.overview-metadata__tags {
  display: flex;
  justify-content: flex-end;
  gap: 5px;
  flex-wrap: wrap;
}

@media (max-width: 420px) {
  .branch-journey {
    align-items: stretch;
    flex-direction: column;
  }

  .branch-journey__line {
    flex-basis: 8px;
    width: 1px;
    height: auto;
    margin-left: 12px;
  }
}
</style>
