<template>
  <n-card class="task-result-panel" :bordered="false">
    <template #header>
      <span class="panel-title">{{ t('taskView.taskResult') }}</span>
    </template>

    <div class="result-body">
      <!-- MR Card -->
      <div v-if="task.issue?.merge_request_url" class="result-card result-card--mr">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon"><GitMergeOutline /></n-icon>
          {{ t('taskView.mergeRequest') }}
        </div>
        <div class="result-card__content">
          <a :href="task.issue.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link mr-link">
            {{ task.merge_request_title || task.issue.merge_request_url }}
          </a>
          <div v-if="task.issue?.branch_name && task.issue?.target_branch" class="mr-branch-flow">
            <span class="branch-item branch-item--work">{{ task.issue.branch_name }}</span>
            <span class="branch-arrow">→</span>
            <span class="branch-item branch-item--target">{{ task.issue.target_branch }}</span>
          </div>
        </div>
      </div>

      <!-- Error Card (for failed tasks) -->
      <div v-if="task.status === 'failed' && task.error_message" class="result-card result-card--error">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--error"><AlertCircleOutline /></n-icon>
          {{ t('taskView.error') }}
        </div>
        <div class="result-card__content">
          <pre class="error-message">{{ task.error_message }}</pre>
        </div>
      </div>

      <!-- Code Changes -->
      <div v-if="hasChanges" class="result-card result-card--changes">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon"><CodeOutline /></n-icon>
          {{ t('common.changes') }}
        </div>
        <div class="result-card__content changes-row">
          <span class="changes-add">+{{ task.additions || 0 }}</span>
          <span class="changes-del">-{{ task.deletions || 0 }}</span>
          <span class="changes-total">{{ t('taskView.totalSuffix', { total: task.total_changes || 0 }) }}</span>
        </div>
      </div>

      <!-- Execution Summary -->
      <div class="result-card result-card--summary">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon"><TimeOutline /></n-icon>
          {{ t('taskView.executionSummary') }}
        </div>
        <div class="result-card__content summary-grid">
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.modelName') }}</span>
            <span class="summary-value">{{ task.model_name || '-' }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.totalTokens') }}</span>
            <span class="summary-value">{{ totalTokens != null ? totalTokens.toLocaleString() : '-' }}</span>
            <span v-if="task.input_tokens != null && task.output_tokens != null" class="summary-item__sub">
              {{ t('taskView.tokenBreakdown', { input: task.input_tokens.toLocaleString(), output: task.output_tokens.toLocaleString() }) }}
            </span>
          </div>
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.duration') }}</span>
            <span class="summary-value">{{ executionDuration }}</span>
          </div>
        </div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NIcon } from 'naive-ui'
import { GitMergeOutline, AlertCircleOutline, CodeOutline, TimeOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../api'

const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()

const hasChanges = computed(() =>
  props.task.additions !== undefined || props.task.deletions !== undefined
)

const executionDuration = computed(() => {
  if (!props.task.started_at || !props.task.completed_at) return '-'
  try {
    const startMs = new Date(props.task.started_at).getTime()
    const endMs = new Date(props.task.completed_at).getTime()
    const diffSeconds = Math.max(0, Math.round((endMs - startMs) / 1000))
    if (diffSeconds < 60) return `${diffSeconds}s`
    const minutes = Math.floor(diffSeconds / 60)
    const seconds = diffSeconds % 60
    return seconds > 0 ? `${minutes}m${seconds}s` : `${minutes}m`
  } catch {
    return '-'
  }
})

const totalTokens = computed(() => {
  const i = props.task.input_tokens
  const o = props.task.output_tokens
  if (i == null && o == null) return null
  return (i ?? 0) + (o ?? 0)
})
</script>

<style scoped>
.task-result-panel {
  border-radius: var(--app-card-radius);
}

.panel-title {
  font-size: 18px;
  font-weight: 600;
}

.result-body {
  display: grid;
  gap: 14px;
}

.result-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid rgba(128, 128, 128, 0.1);
  background: rgba(128, 128, 128, 0.03);
}

.result-card--mr {
  border-color: rgba(5, 150, 105, 0.2);
  background: rgba(5, 150, 105, 0.04);
}

.result-card--error {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(239, 68, 68, 0.04);
}

.result-card--changes {
  border-color: rgba(128, 128, 128, 0.15);
}

.result-card--summary {
  border-color: rgba(128, 128, 128, 0.12);
}

.result-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-2, #666);
  margin-bottom: 10px;
}

.result-card__icon {
  color: var(--n-text-color-3, #999);
}

.result-card__icon--error {
  color: #ef4444;
}

.result-card__content {
  font-size: 14px;
}

.mr-link {
  font-weight: 500;
  word-break: break-all;
}

.mr-branch-flow {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.branch-item {
  padding: 2px 7px;
  border-radius: 4px;
  font-size: 12px;
  font-family: var(--n-font-family-mono, monospace);
}

.branch-item--work {
  background: rgba(5, 150, 105, 0.1);
  color: #059669;
}

.branch-item--target {
  background: rgba(124, 58, 237, 0.1);
  color: #7c3aed;
}

.branch-arrow {
  color: var(--n-text-color-3, #999);
  font-size: 12px;
}

.error-message {
  margin: 0;
  padding: 10px;
  font-size: 12px;
  font-family: var(--n-font-family-mono, monospace);
  background: rgba(239, 68, 68, 0.06);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #dc2626;
  max-height: 200px;
  overflow-y: auto;
}

.changes-row {
  display: flex;
  align-items: center;
  gap: 14px;
  font-size: 16px;
  font-weight: 600;
}

.changes-add {
  color: #18a053;
}

.changes-del {
  color: #db3b21;
}

.changes-total {
  font-size: 13px;
  font-weight: 400;
  color: var(--n-text-color-3, #999);
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.summary-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--n-text-color-3, #999);
}

.summary-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.summary-item__sub {
  font-size: 12px;
  color: var(--n-text-color-3, #999);
  margin-top: 2px;
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.app-link:hover {
  text-decoration: underline;
}
</style>
