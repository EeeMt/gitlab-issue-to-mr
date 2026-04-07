<template>
  <n-card class="task-metadata-panel" :bordered="false">
    <template #header>
      <div class="panel-header">
        <span class="panel-title">{{ t('taskView.taskMetadata') }}</span>
        <div class="panel-badges">
          <n-tag :type="statusColors[task.status] ?? 'default'" round size="small">
            {{ t(`status.${task.status}`) }}
          </n-tag>
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
            <GitMergeOutline v-if="task.issue_iid" />
            <PersonOutline v-else />
          </n-icon>
          {{ t('common.source') }}
        </span>
        <span class="metadata-value">
          <template v-if="task.issue_iid && task.issue_url">
            <a :href="task.issue_url" target="_blank" rel="noopener noreferrer" class="app-link">
              #{{ task.issue_iid }}
            </a>
            <span v-if="task.initiator_username" class="metadata-initiator"> · {{ task.initiator_username }}</span>
          </template>
          <template v-else-if="task.issue_iid">
            #{{ task.issue_iid }}
            <span v-if="task.initiator_username" class="metadata-initiator"> · {{ task.initiator_username }}</span>
          </template>
          <template v-else>
            <span class="metadata-manual">{{ t('taskView.manualCreation') }}</span>
            <span v-if="task.initiator_username" class="metadata-initiator"> · {{ task.initiator_username }}</span>
          </template>
        </span>
      </div>

      <!-- Branch flow -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
          {{ t('taskView.branchFlow') }}
        </span>
        <span class="metadata-value">
          <span class="branch-flow">
            <span v-if="task.base_branch" class="branch-item branch-item--base">{{ task.base_branch }}</span>
            <span v-if="task.base_branch && task.branch_name" class="branch-arrow">➜</span>
            <span v-if="task.branch_name" class="branch-item branch-item--work">
              <a v-if="task.branch_url" :href="task.branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.branch_name }}</a>
              <span v-else>{{ task.branch_name }}</span>
            </span>
            <span v-if="task.branch_name" class="branch-arrow">➜</span>
            <span v-if="task.target_branch" class="branch-item branch-item--target">
              <a v-if="task.target_branch_url" :href="task.target_branch_url" target="_blank" rel="noopener noreferrer" class="app-link">{{ task.target_branch }}</a>
              <span v-else>{{ task.target_branch }}</span>
            </span>
            <span v-else class="branch-item branch-item--direct">{{ t('taskView.directPush') }}</span>
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
          <!-- Completed with MR -->
          <template v-if="task.merge_request_url">
            <a :href="task.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link mr-link">
              {{ task.merge_request_title || `MR !${task.merge_request_iid}` }}
            </a>
          </template>
          <!-- Will create MR (target branch set, not yet done) -->
          <template v-else-if="task.target_branch">
            <span class="mr-pending">{{ t('taskView.mrWillBeCreated') }} → <span class="branch-item branch-item--target" style="display:inline">{{ task.target_branch }}</span></span>
          </template>
          <!-- No MR -->
          <template v-else>
            <span class="mr-none">{{ t('taskView.mrNotCreated') }}</span>
          </template>
        </span>
      </div>

      <!-- User prompt -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><ChatbubbleOutline /></n-icon>
          {{ t('taskView.userPrompt') }}
        </span>
        <pre class="metadata-prompt">{{ task.user_prompt }}</pre>
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
  ChatbubbleOutline,
  TimeOutline,
  GitPullRequest
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../api'
import { formatPriority } from '../utils/format'
import { formatDateTimeUtc8 } from '../utils/datetime'

const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

const projectDisplayName = computed(() => {
  return props.task.project_path_with_namespace
    || props.task.project_name
    || `Project #${props.task.project_id}`
})

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
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
  gap: 14px;
}

.metadata-row {
  display: flex;
  gap: 12px;
  align-items: baseline;
}

.metadata-label {
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  min-width: 90px;
  flex-shrink: 0;
}

.metadata-value {
  font-size: 14px;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.metadata-manual {
  color: var(--n-text-color-2, #666);
}

.metadata-initiator {
  color: var(--n-text-color-3, #999);
  font-size: 13px;
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

.metadata-prompt {
  margin: 0;
  padding: 12px;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  line-height: 1.6;
  background: rgba(128, 128, 128, 0.05);
  border-radius: 8px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 280px;
  overflow-y: auto;
  border: 1px solid rgba(128, 128, 128, 0.12);
  color: var(--n-text-color-2);
  flex: 1;
  min-width: 0;
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
