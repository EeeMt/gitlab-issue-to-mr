<template>
  <n-card class="task-continuation-panel" :bordered="false">
    <template #header>
      <div class="panel-header">
        <div>
          <div class="panel-eyebrow">{{ t('taskView.nextStep') }}</div>
          <div class="panel-title">
            {{ canAppendFollowupTask ? t('taskView.appendFollowupTitle') : t('taskView.continueGuideTitle') }}
          </div>
        </div>
        <n-icon size="18" class="panel-icon"><GitCompareOutline /></n-icon>
      </div>
    </template>

    <p class="continuation-hint">
      {{ canAppendFollowupTask ? t('taskView.appendFollowupHint') : t('taskView.continueGuideHint') }}
    </p>
    <div class="continuation-actions">
      <n-button
        :type="canAppendFollowupTask ? 'default' : 'primary'"
        size="small"
        secondary
        strong
        @click="goToIssue"
      >
        <template #icon><n-icon :component="ArrowBackOutline" /></template>
        {{ t('taskView.backToIssue') }}
      </n-button>
      <n-button
        v-if="canAppendFollowupTask"
        type="primary"
        size="small"
        strong
        @click="emit('append-followup-task')"
      >
        <template #icon><n-icon :component="AddCircleOutline" /></template>
        {{ t('taskView.appendFollowupTask') }}
      </n-button>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { NButton, NCard, NIcon } from 'naive-ui'
import { AddCircleOutline, ArrowBackOutline, GitCompareOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import type { Task } from '../api'

const props = defineProps<{
  task: Task
  canAppendFollowupTask?: boolean
}>()

const emit = defineEmits<{
  (event: 'append-followup-task'): void
}>()

const { t } = useI18n()
const router = useRouter()

function goToIssue() {
  if (props.task.issue_id) router.push(`/issues/${props.task.issue_id}`)
}
</script>

<style scoped>
.task-continuation-panel {
  border-radius: var(--app-card-radius);
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.panel-eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: uppercase;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
}

.panel-icon {
  color: rgba(71, 85, 105, 0.7);
}

.continuation-hint {
  margin: 0;
  color: var(--n-text-color-2);
  font-size: 12px;
  line-height: 1.55;
}

.continuation-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  margin-top: 14px;
}

.continuation-actions :deep(.n-button:only-child) {
  grid-column: 1 / -1;
}

@media (max-width: 420px) {
  .continuation-actions {
    grid-template-columns: 1fr;
  }
}
</style>
