<template>
  <n-card class="execution-card" :bordered="false" data-testid="issue-current-execution">
    <template #header>
      <div class="execution-card__header">
        <div>
          <div class="execution-card__eyebrow">
            {{ isActive ? t('issue.currentExecution') : t('issue.latestExecution') }}
          </div>
          <div v-if="task" class="execution-card__title">Task #{{ task.id }}</div>
          <div v-else class="execution-card__title">{{ t('issue.noExecutionYet') }}</div>
        </div>
        <n-tag v-if="task" :type="statusColors[task.status]" size="small" round>
          {{ t(`status.${task.status}`) }}
        </n-tag>
      </div>
    </template>

    <button
      v-if="task"
      type="button"
      class="execution-card__body"
      :aria-label="t('issue.executionOpenTask', { id: task.id })"
      @click="emit('open-task', task.id)"
    >
      <div class="execution-card__prompt">{{ task.user_prompt }}</div>
      <div class="execution-card__meta">
        <span>
          {{ t('issue.executionMode') }} ·
          {{ task.task_mode === 'plan' ? t('issue.taskModePlan') : t('issue.taskModeExecute') }}
        </span>
        <span>{{ t('dashboard.duration') }} · {{ duration }}</span>
        <span>
          {{ task.started_at ? t('issue.executionStartedAt') : t('issue.executionCreatedAt') }}
          · {{ formatCompactDateTime(task.started_at || task.created_at) }}
        </span>
        <span v-if="queueContextLabel">{{ queueContextLabel }}</span>
      </div>
      <span class="execution-card__link">{{ t('issue.executionOpenTask', { id: task.id }) }} →</span>
    </button>

    <div v-else class="execution-card__empty">{{ t('issue.noExecutionHint') }}</div>
    <div v-if="isActive" class="execution-card__activity" aria-hidden="true"></div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NTag } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Task } from '../../api'
import { formatDateTimeUtc8Compact, parseUtcDate } from '../../utils/datetime'
import { formatDurationMs } from '../../utils/format'

const props = defineProps<{
  task: Task | null
  isActive: boolean
}>()

const emit = defineEmits<{
  (event: 'open-task', taskId: number): void
}>()

const { t } = useI18n()

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default',
}

const duration = computed(() => {
  const task = props.task
  if (!task?.started_at) return '—'
  const started = parseUtcDate(task.started_at).getTime()
  const ended = task.completed_at ? parseUtcDate(task.completed_at).getTime() : Date.now()
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) return '—'
  return formatDurationMs(ended - started)
})

const queueContextLabel = computed(() => {
  const task = props.task
  if (!task) return null
  const qp = task.queue_position
  const blockedBy = task.blocked_by_task_id
  if (task.waiting_reason === 'sequence_repair_required') {
    return t('taskView.queueContextSequenceRepair')
  }
  if (task.waiting_reason === 'workspace_cleanup') {
    return t('taskView.queueContextWaitingCleanup', {
      blockedBy: task.lock_owner_task_id ?? '',
    })
  }
  if (typeof qp === 'number' && qp > 1) {
    return t('taskView.queueContextNonHead', { position: qp, blockedBy: blockedBy ?? '' })
  }
  if (qp === 1) {
    return task.scheduled_at ? t('taskView.queueContextHeadScheduled') : t('taskView.queueContextHeadDue')
  }
  return null
})

function formatCompactDateTime(value?: string | null): string {
  return value ? formatDateTimeUtc8Compact(value) : '—'
}
</script>

<style scoped>
.execution-card {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(37, 99, 235, 0.11);
  border-radius: var(--app-card-radius);
  background:
    radial-gradient(circle at 92% 0%, rgba(37, 99, 235, 0.09), transparent 34%),
    linear-gradient(145deg, rgba(255, 255, 255, 0.98), rgba(248, 250, 252, 0.96));
}

.execution-card__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.execution-card__eyebrow {
  margin-bottom: 4px;
  color: rgba(37, 99, 235, 0.78);
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.execution-card__title {
  color: var(--n-text-color-1);
  font-size: 18px;
  font-weight: 650;
}

.execution-card__body {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 9px 18px;
  width: 100%;
  padding: 0;
  border: 0;
  background: transparent;
  color: inherit;
  cursor: pointer;
  text-align: left;
}

.execution-card__prompt {
  min-width: 0;
  overflow: hidden;
  color: rgba(15, 23, 42, 0.86);
  font-size: 14px;
  font-weight: 550;
  line-height: 1.5;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.execution-card__meta {
  display: flex;
  grid-column: 1;
  gap: 6px 14px;
  flex-wrap: wrap;
  color: var(--n-text-color-3);
  font-size: 12px;
}

.execution-card__link {
  grid-column: 2;
  grid-row: 1 / 3;
  align-self: center;
  color: var(--n-primary-color, #18a058);
  font-size: 13px;
  white-space: nowrap;
  transition: transform 160ms ease, opacity 160ms ease;
}

.execution-card__body:hover .execution-card__link {
  transform: translateX(3px);
}

.execution-card__empty {
  color: var(--n-text-color-3);
  font-size: 13px;
}

.execution-card__activity {
  position: absolute;
  right: 0;
  bottom: 0;
  left: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, #2563eb, #18a058, transparent);
  transform: translateX(-55%);
  animation: execution-activity 2.6s ease-in-out infinite;
}

@media (prefers-reduced-motion: reduce) {
  .execution-card__activity {
    animation: none;
  }
}

@keyframes execution-activity {
  50% { transform: translateX(55%); }
}

@media (max-width: 640px) {
  .execution-card__body {
    grid-template-columns: minmax(0, 1fr);
  }

  .execution-card__prompt {
    white-space: normal;
  }

  .execution-card__link {
    grid-column: 1;
    grid-row: auto;
    justify-self: start;
  }
}
</style>
