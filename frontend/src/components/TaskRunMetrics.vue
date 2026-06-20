<template>
  <n-card class="task-run-metrics" :bordered="false">
    <template #header>
      <div class="panel-header">
        <div>
          <div class="panel-eyebrow">{{ t('taskView.executionData') }}</div>
          <div class="panel-title">{{ t('taskView.runStatistics') }}</div>
        </div>
        <n-icon size="18" class="panel-icon"><PulseOutline /></n-icon>
      </div>
    </template>

    <div class="metrics-grid">
      <div class="metric-item metric-item--wide">
        <span class="metric-label">{{ t('taskView.modelName') }}</span>
        <strong class="metric-value metric-value--model">{{ task.model_name || '-' }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">{{ t('taskView.duration') }}</span>
        <strong class="metric-value">{{ executionDuration }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">{{ t('taskView.totalTokens') }}</span>
        <strong class="metric-value">{{ totalTokens != null ? formatLargeNumber(totalTokens) : '-' }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">{{ t('taskView.inputTokens') }}</span>
        <strong class="metric-value">{{ task.input_tokens != null ? formatLargeNumber(task.input_tokens) : '-' }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">{{ t('taskView.outputTokens') }}</span>
        <strong class="metric-value">{{ task.output_tokens != null ? formatLargeNumber(task.output_tokens) : '-' }}</strong>
      </div>
      <div v-if="contextCompactCount != null" class="metric-item">
        <span class="metric-label">{{ t('taskView.contextCompactCount') }}</span>
        <strong class="metric-value">{{ t('taskView.contextCompactMetric', { count: contextCompactCount }) }}</strong>
      </div>
      <div class="metric-item">
        <span class="metric-label">{{ t('taskView.skillUsage') }}</span>
        <strong class="metric-value">{{ skillUsageTotal > 0 ? t('taskView.skillUsageCount', { count: skillUsageTotal }) : '-' }}</strong>
      </div>
    </div>

    <div v-if="skillUsageStats.length > 0" class="metrics-detail metrics-detail--skills">
      {{ skillUsageBreakdown }}
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NIcon } from 'naive-ui'
import { PulseOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../api'
import type { SkillUsageStat } from './task-process/taskProcessUtils'
import { formatLargeNumber } from '../utils/usageLimits'

const props = defineProps<{
  task: Task
  contextCompactCount?: number
  skillUsageStats?: SkillUsageStat[]
}>()

const { t } = useI18n()

const totalTokens = computed(() => {
  const input = props.task.input_tokens
  const output = props.task.output_tokens
  if (input == null && output == null) return null
  return (input ?? 0) + (output ?? 0)
})

const executionDuration = computed(() => {
  if (!props.task.started_at || !props.task.completed_at) return '-'
  const startMs = new Date(props.task.started_at).getTime()
  const endMs = new Date(props.task.completed_at).getTime()
  if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return '-'
  const diffSeconds = Math.max(0, Math.round((endMs - startMs) / 1000))
  if (diffSeconds < 60) return `${diffSeconds}s`
  const minutes = Math.floor(diffSeconds / 60)
  const seconds = diffSeconds % 60
  return seconds > 0 ? `${minutes}m${seconds}s` : `${minutes}m`
})

const skillUsageStats = computed(() => props.skillUsageStats ?? [])
const skillUsageTotal = computed(() =>
  skillUsageStats.value.reduce((total, skill) => total + skill.count, 0)
)
const skillUsageBreakdown = computed(() =>
  skillUsageStats.value
    .map(skill => `${skill.name}: ${t('taskView.skillUsageCount', { count: skill.count })}`)
    .join(' · ')
)
</script>

<style scoped>
.task-run-metrics {
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

.metrics-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 1px;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.08);
}

.metric-item {
  display: grid;
  gap: 4px;
  min-width: 0;
  padding: 10px 12px;
  background: var(--n-color, #fff);
}

.metric-item--wide {
  grid-column: 1 / -1;
}

.metric-label {
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.35;
}

.metric-value {
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 15px;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.metric-value--model {
  font-size: 13px;
}

.metrics-detail {
  margin-top: 10px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.55;
}

.metrics-detail--skills {
  margin-top: 4px;
  overflow-wrap: anywhere;
}
</style>
