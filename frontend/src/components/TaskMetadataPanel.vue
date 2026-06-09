<template>
  <n-card class="task-metadata-panel" :bordered="false">
    <template #header>
      <div class="panel-header">
        <span class="panel-title">{{ t('taskView.taskMetadata') }}</span>
        <div class="panel-badges">
          <n-tag type="default" round size="small">{{ formatPriority(task.priority) }}</n-tag>
        </div>
      </div>
    </template>

    <div class="metadata-body">
      <!-- Project -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><FolderOpenOutline /></n-icon>
          {{ t('common.project') }}
        </span>
        <span class="metadata-value">
          <a v-if="task.project_url" :href="task.project_url" target="_blank" rel="noopener noreferrer" class="app-link">
            {{ projectDisplayName }}
          </a>
          <span v-else>{{ projectDisplayName }}</span>
        </span>
      </div>

      <!-- Source -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon">
            <GitMergeOutline v-if="task.issue" />
            <PersonOutline v-else />
          </n-icon>
          {{ t('common.source') }}
        </span>
        <span class="metadata-value">
          <template v-if="task.issue">
            <router-link :to="`/issues/${task.issue.id}`" class="app-link task-issue-link">
              <span class="task-issue-link__id">#{{ task.issue.id }}</span>
              <span class="task-issue-link__title">{{ task.issue.title }}</span>
            </router-link>
          </template>
          <template v-else>
            <span class="metadata-manual">{{ t('taskView.manualCreation') }}</span>
          </template>
        </span>
      </div>

      <!-- Initiator -->
      <div v-if="task.initiator_username" class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><PersonOutline /></n-icon>
          {{ t('common.initiator') }}
        </span>
        <span class="metadata-value">{{ task.initiator_username }}</span>
      </div>

      <!-- Retry Source -->
      <div v-if="task.is_retry && task.retry_source_task_id" class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><RefreshOutline /></n-icon>
          {{ t('taskView.retryOf') }}
        </span>
        <span class="metadata-value">
          <router-link :to="`/tasks/${task.retry_source_task_id}`" class="app-link">
            Task #{{ task.retry_source_task_id }}
          </router-link>
        </span>
      </div>

      <!-- Provider -->
      <div v-if="task.provider_name || task.provider_id" class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><ServerOutline /></n-icon>
          {{ t('taskView.provider') }}
        </span>
        <span class="metadata-value">
          {{ task.provider_name || t('config.providers.systemDefault') }}
        </span>
      </div>

      <!-- Task mode -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><PlayOutline /></n-icon>
          {{ t('taskView.taskMode') }}
        </span>
        <span class="metadata-value">{{ formatTaskMode(task.task_mode) }}</span>
      </div>

      <!-- Branch flow -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
          {{ t('taskView.branchFlow') }}
        </span>
        <span class="metadata-value">
          <span class="branch-flow">
            <template v-if="task.issue?.base_branch">
              <a v-if="branchUrl(task.issue.base_branch)" :href="branchUrl(task.issue.base_branch)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--base app-link">{{ task.issue.base_branch }}</a>
              <span v-else class="branch-item branch-item--base">{{ task.issue.base_branch }}</span>
            </template>
            <span v-if="task.issue?.base_branch && task.issue?.branch_name" class="branch-arrow">➜</span>
            <template v-if="task.issue?.branch_name">
              <a v-if="branchUrl(task.issue.branch_name)" :href="branchUrl(task.issue.branch_name)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--work app-link">{{ task.issue.branch_name }}</a>
              <span v-else class="branch-item branch-item--work">{{ task.issue.branch_name }}</span>
            </template>
            <span v-if="task.issue?.branch_name && task.issue?.target_branch" class="branch-arrow">➜</span>
            <template v-if="task.issue?.target_branch">
              <a v-if="branchUrl(task.issue.target_branch)" :href="branchUrl(task.issue.target_branch)!" target="_blank" rel="noopener noreferrer" class="branch-item branch-item--target app-link">{{ task.issue.target_branch }}</a>
              <span v-else class="branch-item branch-item--target">{{ task.issue.target_branch }}</span>
            </template>
            <span v-if="!task.issue?.branch_name" class="branch-item branch-item--direct">{{ t('taskView.directPush') }}</span>
          </span>
        </span>
      </div>

      <!-- Merge Request -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><GitPullRequest /></n-icon>
          {{ t('taskView.mergeRequest') }}
        </span>
        <span class="metadata-value">
          <template v-if="task.issue?.merge_request_url">
            <a :href="task.issue.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link mr-link">
              {{ task.issue.merge_request_iid ? `!${task.issue.merge_request_iid}` : t('taskView.mergeRequest') }}
            </a>
          </template>
          <template v-else-if="task.issue?.target_branch">
            <span class="mr-pending">{{ t('taskView.mrWillBeCreated') }} → <span class="branch-item branch-item--target" style="display:inline">{{ task.issue.target_branch }}</span></span>
          </template>
          <template v-else>
            <span class="mr-none">{{ t('taskView.mrNotCreated') }}</span>
          </template>
        </span>
      </div>

      <!-- Time axis -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><TimeOutline /></n-icon>
          {{ t('common.timeline') }}
        </span>
        <div class="time-axis">
          <div class="time-point">
            <span class="time-point__label">{{ t('common.created') }}</span>
            <span class="time-point__value">{{ formatDate(task.created_at) }}</span>
          </div>
          <template v-if="task.scheduled_at && isSignificantSchedule(task.scheduled_at, task.created_at)">
            <div class="time-axis__sep">→</div>
            <div class="time-point">
              <span class="time-point__label">{{ t('common.scheduledAt') }}</span>
              <span class="time-point__value">{{ formatDate(task.scheduled_at) }}</span>
            </div>
          </template>
          <template v-if="task.started_at">
            <div class="time-axis__sep">→</div>
            <div class="time-point">
              <span class="time-point__label">{{ t('common.started') }}</span>
              <span class="time-point__value">{{ formatDate(task.started_at) }}</span>
            </div>
          </template>
          <template v-if="task.completed_at">
            <div class="time-axis__sep">→</div>
            <div class="time-point">
              <span class="time-point__label">{{ t('taskView.completedAt') }}</span>
              <span class="time-point__value">{{ formatDate(task.completed_at) }}</span>
            </div>
          </template>
        </div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NTag, NIcon } from 'naive-ui'
import {
  FolderOpenOutline,
  GitMergeOutline,
  PersonOutline,
  GitBranchOutline,
  TimeOutline,
  GitPullRequest,
  RefreshOutline,
  ServerOutline,
  PlayOutline
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../api'
import { formatPriority } from '../utils/format'
import { formatDateTimeUtc8 } from '../utils/datetime'


const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()

const projectDisplayName = computed(() => {
  return props.task.project_path_with_namespace
    || props.task.project_name
    || `Project #${props.task.project_id}`
})

function branchUrl(branchName: string): string | null {
  if (!props.task.project_url || !branchName) return null
  return `${props.task.project_url}/-/tree/${encodeURIComponent(branchName)}`
}

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
}

function formatTaskMode(mode?: Task['task_mode'] | null): string {
  return mode === 'plan' ? t('taskView.taskModePlan') : t('taskView.taskModeExecute')
}

function isSignificantSchedule(scheduledAt: string, createdAt: string): boolean {
  try {
    const diff = Math.abs(new Date(scheduledAt).getTime() - new Date(createdAt).getTime())
    return diff > 60 * 1000 // more than 60 seconds difference
  } catch {
    return false
  }
}
</script>

<style scoped>
.task-metadata-panel {
  border-radius: var(--app-card-radius);
  height: 100%;
}

.panel-header {
  display: flex;
  align-items: center;
  gap: 10px;
  flex-wrap: wrap;
}

.panel-title {
  font-size: 18px;
  font-weight: 600;
}

.panel-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.metadata-body {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 12px;
  row-gap: 14px;
  align-items: center;
}

.metadata-row {
  display: contents;
}

.metadata-label {
  display: inline-flex;
  align-items: center;
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  white-space: nowrap;
}

.metadata-row > :last-child {
  min-width: 0;
}

.metadata-value {
  min-width: 0;
  font-size: 14px;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.metadata-manual {
  color: var(--n-text-color-2, #666);
}

.branch-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.branch-item {
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  background: rgba(128, 128, 128, 0.08);
}

.branch-item--base {
  background: rgba(2, 132, 199, 0.08);
  color: #0284c7;
}

.branch-item--work {
  background: rgba(5, 150, 105, 0.08);
  color: #059669;
}

.branch-item--target {
  background: rgba(124, 58, 237, 0.08);
  color: #7c3aed;
}

.branch-item--direct {
  background: rgba(128, 128, 128, 0.08);
  color: var(--n-text-color-3, #999);
  font-style: italic;
  font-family: inherit;
}

.branch-arrow {
  color: var(--n-text-color-3, #999);
  font-size: 12px;
}

.time-axis {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
  gap: 6px 8px;
}

.time-axis__sep {
  color: var(--n-text-color-3, #999);
  margin-top: 2px;
  flex-shrink: 0;
}

.time-point {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 0 0 auto;
  min-width: 0;
}

.time-point__label {
  font-size: 11px;
  color: var(--n-text-color-3, #999);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}

.time-point__value {
  font-size: 13px;
  color: var(--n-text-color-2);
}

@media (max-width: 600px) {
  .time-point__value {
    font-size: 11px;
  }
  .time-point {
    padding: 2px 0;
  }
  .time-axis__sep {
    display: none;
  }
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.app-link:hover {
  text-decoration: underline;
}

.task-issue-link {
  --task-issue-link-color: #3b82f6;
  --task-issue-link-border: rgba(37, 99, 235, 0.28);
  --task-issue-link-bg: rgba(37, 99, 235, 0.12);
  --task-issue-link-hover-border: rgba(37, 99, 235, 0.44);
  --task-issue-link-hover-bg: rgba(37, 99, 235, 0.18);

  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  max-width: 100%;
  padding: 3px 10px;
  border: 1px solid var(--task-issue-link-border);
  border-radius: 999px;
  background: var(--task-issue-link-bg);
  color: var(--task-issue-link-color);
  font-weight: 400;
  line-height: 1.45;
  vertical-align: middle;
  transition:
    background 0.15s ease,
    border-color 0.15s ease,
    color 0.15s ease;
}

.task-issue-link:hover {
  border-color: var(--task-issue-link-hover-border);
  background: var(--task-issue-link-hover-bg);
  text-decoration: none;
}

.task-issue-link__id {
  flex: 0 0 auto;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  font-weight: 500;
}

.task-issue-link__title {
  min-width: 0;
  overflow-wrap: anywhere;
}

.metadata-label-icon {
  vertical-align: middle;
  margin-right: 3px;
  opacity: 0.65;
}

.mr-link {
  font-size: 14px;
}

.mr-pending {
  font-size: 13px;
  color: var(--n-text-color-2);
}

.mr-none {
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  font-style: italic;
}
</style>
