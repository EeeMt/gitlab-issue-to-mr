<template>
  <n-card class="issue-task-panel" :bordered="false" data-testid="issue-tasks-card">
    <template #header>
      <div class="issue-task-panel__header">
        <div>
          <div class="issue-task-panel__eyebrow">{{ t('issue.executionHistory') }}</div>
          <div class="issue-task-panel__title">
            {{ t('issue.taskCount', { count: tasks.length }) }}
          </div>
        </div>
        <span class="issue-task-panel__hint">{{ t('issue.executionHistoryHint') }}</span>
      </div>
    </template>

    <n-data-table
      class="issue-task-panel__table"
      :columns="columns"
      :data="tasks"
      :row-key="(row: Task) => row.id"
      :row-props="rowProps"
      :bordered="false"
      size="small"
    />
  </n-card>
</template>

<script setup lang="ts">
import { NCard, NDataTable, type DataTableColumns } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { Task } from '../../api'

defineProps<{
  tasks: Task[]
  columns: DataTableColumns<Task>
  rowProps: (row: Task) => Record<string, unknown>
}>()

const { t } = useI18n()
</script>

<style scoped>
.issue-task-panel {
  width: 100%;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  border-radius: var(--app-card-radius);
}

.issue-task-panel :deep(.n-card__content),
.issue-task-panel :deep(.n-card-content) {
  min-width: 0;
  overflow: hidden;
}

.issue-task-panel__header {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 12px;
}

.issue-task-panel__eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.issue-task-panel__title {
  color: var(--n-text-color-1);
  font-size: 18px;
  font-weight: 650;
}

.issue-task-panel__hint {
  max-width: 320px;
  color: var(--n-text-color-3);
  font-size: 12px;
  text-align: right;
}

.issue-task-panel__table :deep(.n-data-table-th) {
  padding: 7px 9px;
  font-size: 11px;
  font-weight: 600;
}

.issue-task-panel__table {
  width: 100%;
  min-width: 0;
  max-width: 100%;
}

.issue-task-panel__table :deep(table) {
  width: 100%;
  table-layout: fixed;
}

.issue-task-panel__table :deep(.n-data-table-td) {
  padding: 7px 9px;
  font-size: 12px;
  line-height: 1.3;
}

.issue-task-panel__table :deep(.n-data-table-tr:hover .n-data-table-td) {
  background: rgba(15, 23, 42, 0.025);
}

@media (max-width: 640px) {
  .issue-task-panel__header {
    align-items: flex-start;
    flex-direction: column;
  }

  .issue-task-panel__hint {
    text-align: left;
  }
}
</style>
