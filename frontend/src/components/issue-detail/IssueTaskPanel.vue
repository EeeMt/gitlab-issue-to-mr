<template>
  <n-card class="issue-task-panel" :bordered="false" data-testid="issue-tasks-card">
    <template #header>
      <div class="issue-task-panel__header">
        <div class="issue-task-panel__heading">
          <div class="issue-task-panel__title">{{ t('issue.executionHistory') }}</div>
          <span class="issue-task-panel__count">{{ t('issue.taskCount', { count: tasks.length }) }}</span>
        </div>
      </div>
    </template>

    <ol
      v-if="tasks.length"
      class="issue-task-panel__list"
      data-testid="issue-task-list"
    >
      <li
        v-for="(task, index) in tasks"
        :key="task.id"
        class="issue-task-panel__item"
        :class="[
          `issue-task-panel__item--${task.status}`,
          { 'issue-task-panel__item--last': index === tasks.length - 1 },
        ]"
      >
        <span class="issue-task-panel__rail" aria-hidden="true">
          <span class="issue-task-panel__marker"></span>
        </span>
        <IssueTaskRecord
          :task="task"
          :retry-task="retriedTaskMap.get(task.id)"
          :can-reschedule="canManageTask(task) && canRescheduleTask(task)"
          :can-retry="canManageTask(task) && ['failed', 'cancelled'].includes(task.status)"
          @open="emit('open-task', $event)"
          @retry="emit('retry-task', $event)"
          @reschedule="emit('reschedule-task', $event)"
        />
      </li>
    </ol>

    <div v-else class="issue-task-panel__empty">
      <span class="issue-task-panel__empty-marker" aria-hidden="true"></span>
      <div>
        <div class="issue-task-panel__empty-title">{{ t('issue.noExecutionYet') }}</div>
        <div class="issue-task-panel__empty-hint">{{ t('issue.noExecutionHint') }}</div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { NCard } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Task } from '../../api'
import IssueTaskRecord from './IssueTaskRecord.vue'

defineProps<{
  tasks: Task[]
  retriedTaskMap: ReadonlyMap<number, Task>
  canManageTask: (task: Task) => boolean
  canRescheduleTask: (task: Task) => boolean
}>()

const emit = defineEmits<{
  (event: 'open-task', taskId: number): void
  (event: 'retry-task', task: Task): void
  (event: 'reschedule-task', task: Task): void
}>()

const { t } = useI18n()
</script>

<style scoped>
.issue-task-panel {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  border: 1px solid var(--n-border-color, rgba(15, 23, 42, 0.065));
  border-radius: var(--app-card-radius);
}

.issue-task-panel :deep(.n-card__content),
.issue-task-panel :deep(.n-card-content) {
  min-width: 0;
  overflow: hidden;
  padding: 0 20px 18px;
}

.issue-task-panel :deep(.n-card-header) {
  padding: 17px 20px 13px;
}

.issue-task-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.issue-task-panel__heading {
  display: flex;
  align-items: center;
}

.issue-task-panel__title {
  color: var(--n-text-color-1);
  font-size: 17px;
  font-weight: 670;
}

.issue-task-panel__count {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.4;
}

.issue-task-panel__count::before {
  margin: 0 8px;
  color: var(--n-border-color, rgba(15, 23, 42, 0.18));
  content: '·';
}

.issue-task-panel__list {
  position: relative;
  display: grid;
  gap: 0;
  margin: 0;
  padding: 0;
  list-style: none;
}

.issue-task-panel__item {
  --rail-color: #94a3b8;
  position: relative;
  display: grid;
  grid-template-columns: 18px minmax(0, 1fr);
  gap: 10px;
  min-width: 0;
  padding-bottom: 8px;
}

.issue-task-panel__item--queued { --rail-color: #2080f0; }
.issue-task-panel__item--running { --rail-color: #d97706; }
.issue-task-panel__item--completed { --rail-color: #18a058; }
.issue-task-panel__item--failed { --rail-color: #d03050; }
.issue-task-panel__item--cancelled { --rail-color: #94a3b8; }

.issue-task-panel__item--last {
  padding-bottom: 0;
}

.issue-task-panel__rail {
  position: relative;
  z-index: 1;
  display: flex;
  align-items: center;
  justify-content: center;
}

.issue-task-panel__rail::before,
.issue-task-panel__rail::after {
  position: absolute;
  left: 50%;
  width: 1px;
  background: var(--n-divider-color, var(--n-border-color, rgba(148, 163, 184, 0.3)));
  content: '';
  transform: translateX(-0.5px);
}

.issue-task-panel__rail::before {
  top: 0;
  bottom: 50%;
}

.issue-task-panel__rail::after {
  top: 50%;
  bottom: -8px;
}

.issue-task-panel__item:first-child .issue-task-panel__rail::before,
.issue-task-panel__item:last-child .issue-task-panel__rail::after {
  display: none;
}

.issue-task-panel__marker {
  position: relative;
  z-index: 1;
  width: 9px;
  height: 9px;
  box-sizing: border-box;
  border: 2px solid var(--n-color, #fff);
  border-radius: 50%;
  background: var(--rail-color);
  box-shadow: 0 0 0 3px color-mix(in srgb, var(--rail-color) 12%, var(--n-color, #fff));
}

.issue-task-panel__item--running .issue-task-panel__marker::after {
  position: absolute;
  inset: -5px;
  border: 1px solid color-mix(in srgb, var(--rail-color) 54%, transparent);
  border-radius: inherit;
  content: '';
  opacity: 0;
  transform: scale(0.72);
}

@media (prefers-reduced-motion: no-preference) {
  .issue-task-panel__item--running .issue-task-panel__marker::after {
    animation: issue-task-marker-pulse 2.4s ease-out infinite;
  }
}

@keyframes issue-task-marker-pulse {
  45% { opacity: 0.7; }
  100% { opacity: 0; transform: scale(1.45); }
}

.issue-task-panel__empty {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 18px;
  border: 1px dashed var(--n-border-color, rgba(15, 23, 42, 0.12));
  border-radius: 12px;
  background: var(--n-color-embedded, rgba(15, 23, 42, 0.02));
}

.issue-task-panel__empty-marker {
  width: 10px;
  height: 10px;
  flex: 0 0 auto;
  border: 2px solid var(--n-color, #fff);
  border-radius: 50%;
  background: #94a3b8;
  box-shadow: 0 0 0 3px rgba(148, 163, 184, 0.15);
}

.issue-task-panel__empty-title {
  color: var(--n-text-color-1);
  font-size: 13px;
  font-weight: 650;
}

.issue-task-panel__empty-hint {
  margin-top: 2px;
  color: var(--n-text-color-3);
  font-size: 12px;
}

@media (max-width: 640px) {
  .issue-task-panel :deep(.n-card__content),
  .issue-task-panel :deep(.n-card-content) {
    padding: 0 14px 14px;
  }

  .issue-task-panel :deep(.n-card-header) {
    padding: 15px 14px 11px;
  }

  .issue-task-panel__item {
    grid-template-columns: 14px minmax(0, 1fr);
    gap: 7px;
  }

}
</style>
