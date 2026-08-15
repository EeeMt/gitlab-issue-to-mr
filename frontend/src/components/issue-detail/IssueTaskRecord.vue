<template>
  <article
    class="task-history-record"
    :class="`task-history-record--${task.status}`"
    :data-testid="`issue-task-record-${task.id}`"
  >
    <button
      type="button"
      class="task-history-record__open"
      :aria-label="t('issue.executionOpenTask', { id: task.id })"
      @click="emit('open', task.id)"
    >
      <div class="task-history-record__content">
        <span class="task-history-record__status">
          <span class="task-history-record__status-dot" aria-hidden="true"></span>
          <span>{{ t(`status.${task.status}`) }}</span>
        </span>

        <div class="task-history-record__prompt-row">
          <n-tag
            v-if="task.is_retry"
            class="task-history-record__retry-badge"
            size="tiny"
            round
          >
            {{ t('common.retry') }}
          </n-tag>
          <n-tooltip
            placement="top-start"
            trigger="hover"
            :show-arrow="false"
            :content-style="issueDetailTooltipContentStyle"
            :theme-overrides="issueDetailTooltipThemeOverrides"
          >
            <template #trigger>
              <span class="task-history-record__prompt">{{ task.user_prompt || '—' }}</span>
            </template>
            <div class="task-description-tooltip">{{ task.user_prompt || '—' }}</div>
          </n-tooltip>
        </div>

        <span class="task-history-record__id">#{{ task.id }}</span>

        <div class="task-history-record__meta">
          <span class="task-history-record__meta-item">
            <span class="task-history-record__meta-label">{{ timeLabel }}</span>
            <n-tooltip
              placement="top"
              trigger="hover"
              :content-style="issueDetailTooltipContentStyle"
              :theme-overrides="issueDetailTooltipThemeOverrides"
            >
              <template #trigger>
                <span class="task-history-record__meta-value">{{ primaryTime }}</span>
              </template>
              <div class="task-time-tooltip">
                <div>{{ t('common.created') }} · {{ formatCompactDateTime(task.created_at) }}</div>
                <div v-if="task.scheduled_at">
                  {{ t('dashboard.scheduled') }} · {{ formatCompactDateTime(task.scheduled_at) }}
                </div>
              </div>
            </n-tooltip>
          </span>
          <span class="task-history-record__meta-item">
            <span class="task-history-record__meta-label">{{ t('dashboard.duration') }}</span>
            <span class="task-history-record__meta-value">{{ duration }}</span>
          </span>
          <span v-if="queueContextLabel" class="task-history-record__queue-context">
            {{ queueContextLabel }}
          </span>
        </div>
      </div>
    </button>

    <div class="task-history-record__controls">
      <n-button
        class="task-history-record__details-button"
        size="tiny"
        quaternary
        @click="emit('open', task.id)"
      >
        {{ t('issue.executionViewDetails') }}
        <span class="task-history-record__control-arrow" aria-hidden="true">→</span>
      </n-button>

      <div class="task-history-record__action-row">
        <div v-if="retryTask || canReschedule || canRetry" class="task-history-record__actions">
          <span v-if="retryTask" class="task-history-record__retried-as">
            {{ t('issue.retriedAs') }}
            <n-button text type="primary" size="tiny" @click="emit('open', retryTask.id)">
              Task #{{ retryTask.id }}
            </n-button>
          </span>
          <n-button
            v-else-if="canReschedule"
            class="task-history-record__control-button"
            size="tiny"
            quaternary
            @click="emit('reschedule', task)"
          >
            {{ t('taskView.rescheduleTask') }}
            <n-icon class="task-history-record__trailing-icon" :component="CalendarOutline" />
          </n-button>
          <n-button
            v-else-if="canRetry"
            class="task-history-record__control-button"
            size="tiny"
            quaternary
            @click="emit('retry', task)"
          >
            {{ t('issue.retryTask') }}
            <n-icon class="task-history-record__trailing-icon" :component="ArrowRedoOutline" />
          </n-button>
        </div>
      </div>
    </div>
  </article>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NButton, NIcon, NTag, NTooltip } from 'naive-ui'
import { ArrowRedoOutline, CalendarOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../../api'
import { formatDateTimeUtc8Compact, parseUtcDate } from '../../utils/datetime'
import { formatDurationMs } from '../../utils/format'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './tooltip'

const props = defineProps<{
  task: Task
  retryTask?: Task
  canReschedule: boolean
  canRetry: boolean
}>()

const emit = defineEmits<{
  (event: 'open', taskId: number): void
  (event: 'retry', task: Task): void
  (event: 'reschedule', task: Task): void
}>()

const { t } = useI18n()

const timeLabel = computed(() => (
  props.task.scheduled_at ? t('dashboard.scheduled') : t('issue.executionCreatedAt')
))

const primaryTime = computed(() => (
  formatCompactDateTime(props.task.scheduled_at || props.task.created_at)
))

const duration = computed(() => {
  if (!props.task.started_at) return '—'
  const started = parseUtcDate(props.task.started_at).getTime()
  const ended = props.task.completed_at ? parseUtcDate(props.task.completed_at).getTime() : Date.now()
  if (!Number.isFinite(started) || !Number.isFinite(ended) || ended < started) return '—'
  return formatDurationMs(ended - started)
})

function formatCompactDateTime(value?: string | null): string {
  return value ? formatDateTimeUtc8Compact(value) : '—'
}

const queueContextLabel = computed(() => {
  const task = props.task
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
</script>

<style scoped>
.task-history-record {
  --record-accent: #64748b;
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 10px;
  min-width: 0;
  padding: 10px 11px 10px 12px;
  overflow: hidden;
  border: 1px solid var(--n-border-color, #e5e7eb);
  border-radius: 10px;
  background: var(--n-color, #fff);
  transition: border-color 160ms ease, box-shadow 160ms ease, transform 160ms ease;
}

.task-history-record--queued { --record-accent: #2080f0; }
.task-history-record--running { --record-accent: #d97706; }
.task-history-record--completed { --record-accent: #18a058; }
.task-history-record--failed { --record-accent: #d03050; }
.task-history-record--cancelled { --record-accent: #94a3b8; }

.task-history-record__open {
  display: block;
  min-width: 0;
  width: 100%;
  padding: 0;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: inherit;
  cursor: pointer;
  font: inherit;
  text-align: left;
}

.task-history-record__open:focus-visible {
  outline: 2px solid var(--n-primary-color, #18a058);
  outline-offset: 4px;
}

.task-history-record__content {
  display: grid;
  grid-template-columns: 74px minmax(0, 1fr);
  align-items: center;
  gap: 6px 8px;
  min-width: 0;
}

.task-history-record__status,
.task-history-record__prompt-row,
.task-history-record__meta,
.task-history-record__meta-item,
.task-history-record__controls,
.task-history-record__action-row,
.task-history-record__actions,
.task-history-record__retried-as {
  display: flex;
  align-items: center;
}

.task-history-record__prompt-row {
  gap: 6px;
  min-width: 0;
}

.task-history-record__retry-badge {
  flex: 0 0 auto;
}

.task-history-record__status,
.task-history-record__id {
  width: 74px;
  height: 24px;
  box-sizing: border-box;
  border-radius: 7px;
  font-size: 10px;
  font-weight: 620;
  line-height: 1;
  white-space: nowrap;
}

.task-history-record__status {
  justify-content: center;
  gap: 5px;
  padding: 0 6px;
  border: 1px solid color-mix(in srgb, var(--record-accent) 22%, transparent);
  background: color-mix(in srgb, var(--record-accent) 8%, var(--n-color, #fff));
  color: var(--record-accent);
}

.task-history-record__status-dot {
  width: 5px;
  height: 5px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 0 2px color-mix(in srgb, currentColor 12%, transparent);
}

.task-history-record__id {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--n-border-color, #e5e7eb);
  background: var(--n-color-embedded, rgba(15, 23, 42, 0.025));
  color: var(--n-text-color-3);
  font-family: var(--n-font-family-mono, 'SF Mono', monospace);
}

.task-history-record__retry-badge {
  --n-color: #eef2ff !important;
  --n-border: 1px solid #c7d2fe !important;
  --n-text-color: #4338ca !important;
}

.task-history-record__prompt-row :deep(.n-tooltip) {
  display: contents;
}

.task-history-record__prompt {
  display: block;
  min-width: 0;
  overflow: hidden;
  color: var(--n-text-color-1);
  font-size: 13px;
  font-weight: 570;
  line-height: 1.42;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-history-record__meta {
  display: grid;
  grid-template-columns: 190px minmax(90px, 1fr);
  gap: 12px;
  min-width: 0;
}

.task-history-record__meta-item {
  gap: 5px;
  min-width: 0;
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 1.35;
}

.task-history-record__queue-context {
  grid-column: 1 / -1;
  padding: 2px 6px;
  border-radius: 5px;
  background: rgba(32, 128, 240, 0.07);
  color: rgba(29, 78, 216, 0.9);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
}

.task-history-record__meta-label {
  color: var(--n-text-color-3);
}

.task-history-record__meta-value {
  color: var(--n-text-color-2);
  white-space: nowrap;
}

.task-history-record__controls {
  position: relative;
  z-index: 1;
  align-self: stretch;
  align-items: flex-end;
  justify-content: space-between;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.task-history-record__action-row {
  min-height: 26px;
  justify-content: flex-end;
}

.task-history-record__details-button {
  flex: 0 0 auto;
}

.task-history-record__control-arrow {
  display: inline-block;
  margin-left: 3px;
  transition: transform 160ms ease;
}

.task-history-record__controls :deep(.task-history-record__details-button),
.task-history-record__controls :deep(.task-history-record__control-button) {
  --n-height: 26px !important;
  --n-padding: 0 8px !important;
  --n-border-radius: 7px !important;
  --n-font-size: 11px !important;
  --n-font-weight: 600 !important;
  --n-text-color: var(--n-text-color-3) !important;
  --n-text-color-hover: var(--n-text-color-1) !important;
  --n-text-color-focus: var(--n-text-color-1) !important;
  --n-text-color-pressed: var(--n-text-color-1) !important;
}

.task-history-record__trailing-icon {
  margin-left: 4px;
  font-size: 14px;
}

.task-history-record__retried-as {
  gap: 4px;
  color: var(--n-text-color-3);
  font-size: 11px;
  white-space: nowrap;
}

@media (hover: hover) and (pointer: fine) {
  .task-history-record:hover {
    border-color: color-mix(in srgb, var(--record-accent) 24%, var(--n-border-color, #e5e7eb));
    box-shadow: 0 5px 14px rgba(15, 23, 42, 0.055);
    transform: translateY(-1px);
  }

  .task-history-record:hover .task-history-record__control-arrow {
    transform: translateX(3px);
  }
}

@media (max-width: 640px) {
  .task-history-record {
    grid-template-columns: minmax(0, 1fr);
    gap: 8px;
    padding: 10px;
  }

  .task-history-record__prompt {
    display: -webkit-box;
    width: 100%;
    white-space: normal;
    overflow-wrap: anywhere;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
  }

  .task-history-record__meta {
    grid-template-columns: minmax(0, 1fr);
    gap: 4px;
  }

  .task-history-record__controls {
    align-items: flex-start;
  }

  .task-history-record__actions {
    justify-content: flex-start;
  }
}
</style>
