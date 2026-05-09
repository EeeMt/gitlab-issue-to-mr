<template>
  <n-card class="task-result-panel" :bordered="false">
    <template #header>
      <span class="panel-title">{{ t('taskView.taskResult') }}</span>
    </template>

    <div class="result-body">
      <!-- Commit Record Card -->
      <div v-if="task.commit_sha || task.commit_message || hasChanges" class="result-card result-card--commit">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--commit"><GitCommitOutline /></n-icon>
          {{ t('taskView.commitRecord') }}
        </div>
        <div class="result-card__content">
          <div class="commit-meta">
            <a v-if="task.commit_sha && commitUrl" :href="commitUrl" target="_blank" rel="noopener noreferrer" class="commit-sha-chip commit-sha-chip--link">
              <n-icon size="12"><GitCommitOutline /></n-icon>
              <span>{{ task.commit_sha.slice(0, 8) }}</span>
              <n-icon size="11" class="commit-sha-chip__ext"><OpenOutline /></n-icon>
            </a>
            <span v-else-if="task.commit_sha" class="commit-sha-chip">
              <n-icon size="12"><GitCommitOutline /></n-icon>
              <span>{{ task.commit_sha.slice(0, 8) }}</span>
            </span>
            <span v-if="hasChanges" class="commit-stats">
              <span class="changes-add">+{{ task.additions || 0 }}</span>
              <span class="changes-sep"> / </span>
              <span class="changes-del">-{{ task.deletions || 0 }}</span>
            </span>
          </div>
          <pre v-if="task.commit_message" class="commit-message">{{ task.commit_message }}</pre>
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
            <span class="summary-value">{{ totalTokens != null ? formatLargeNumber(totalTokens) : '-' }}</span>
            <span v-if="task.input_tokens != null && task.output_tokens != null" class="summary-item__sub">
              {{ t('taskView.tokenBreakdown', { input: formatLargeNumber(task.input_tokens), output: formatLargeNumber(task.output_tokens) }) }}
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
import { AlertCircleOutline, TimeOutline, GitCommitOutline, OpenOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { formatLargeNumber } from '../utils/usageLimits'
import type { Task } from '../api'

const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()

const commitUrl = computed(() => {
  if (!props.task.commit_sha || !props.task.project_url) return null
  return `${props.task.project_url}/-/commit/${props.task.commit_sha}`
})

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

.result-card--commit {
  border-color: rgba(59, 130, 246, 0.2);
  background: rgba(59, 130, 246, 0.04);
}

.result-card--error {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(239, 68, 68, 0.04);
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

.result-card__icon--commit {
  color: #3b82f6;
}

.result-card__content {
  font-size: 14px;
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

.commit-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.commit-sha-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--n-font-family-mono, monospace);
  font-size: 12.5px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 5px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.18);
  color: var(--n-text-color-2, #555);
  text-decoration: none;
}

.commit-sha-chip--link {
  color: #3b82f6;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.commit-sha-chip--link:hover {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
  text-decoration: none;
}

.commit-sha-chip__ext {
  opacity: 0.55;
}

.commit-stats {
  font-size: 13px;
  font-weight: 600;
  font-family: var(--n-font-family-mono, monospace);
}

.changes-add {
  color: #18a053;
}

.changes-sep {
  color: var(--n-text-color-3, #bbb);
}

.changes-del {
  color: #db3b21;
}

.commit-message {
  margin: 0;
  font-size: 12.5px;
  font-family: var(--n-font-family-mono, monospace);
  padding: 8px 0 0 0;
  border-top: 1px solid rgba(59, 130, 246, 0.15);
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--n-text-color-1, #333);
  line-height: 1.65;
  max-height: 160px;
  overflow-y: auto;
  background: transparent;
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

.summary-value--mono {
  font-family: var(--n-font-family-mono, monospace);
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
</style>
