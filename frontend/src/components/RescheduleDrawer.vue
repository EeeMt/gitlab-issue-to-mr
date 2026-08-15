<template>
  <n-drawer v-model:show="localShow" :width="isMobile ? '100%' : 680" placement="right">
    <n-drawer-content :title="t('taskView.rescheduleTask')" :native-scrollbar="false" closable>
      <div class="reschedule-drawer">
        <div v-if="task && !hideSummary" class="reschedule-drawer__summary">
          <div class="reschedule-drawer__summary-title-row">
            <div class="reschedule-drawer__summary-title">Task #{{ task.id }}</div>
            <n-tooltip trigger="hover" content-style="font-size: 12px">
              <template #trigger>
                <n-button
                  size="small"
                  secondary
                  circle
                  :aria-label="t('taskView.copySource')"
                  @click="copyPromptSource"
                >
                  <template #icon>
                    <n-icon :component="CopyOutline" />
                  </template>
                </n-button>
              </template>
              {{ t('taskView.copySource') }}
            </n-tooltip>
          </div>
          <div class="reschedule-drawer__summary-prompt markdown-content" v-html="renderedPrompt"></div>
        </div>

        <n-form label-placement="top">
          <n-form-item :label="t('taskView.selectRescheduleTime')">
            <n-date-picker
              v-model:value="scheduleDatetime"
              type="datetime"
              clearable
              style="width: 240px; max-width: 100%"
              :is-date-disabled="isDateDisabled"
              :is-time-disabled="isTimeDisabled"
            />
          </n-form-item>
        </n-form>

        <p v-if="scheduleConstraintHint" class="reschedule-drawer__constraint">
          {{ scheduleConstraintHint }}
        </p>

        <div class="reschedule-drawer__schedule-preview">
          <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
          <template v-else>
            <p class="reschedule-drawer__hint">{{ t('taskView.schedulePreviewHint') }}</p>
            <HeatmapChart
              :tasks="scheduledTasks"
              :selected-ms="scheduleDatetime"
              :max-per-slot="slotMaxTasks"
              :enforce-capacity="slotEnforce"
              @cell-click="handleHeatmapCellClick"
            />
          </template>
        </div>
      </div>

      <template #footer>
        <div class="reschedule-drawer__footer">
          <n-button @click="localShow = false">
            {{ t('common.cancel') }}
          </n-button>
          <n-button type="primary" :loading="loading" @click="handleSubmit">
            {{ t('taskView.saveScheduledTime') }}
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { NDrawer, NDrawerContent, NButton, NIcon, NSpin, NForm, NFormItem, NDatePicker, NTooltip, useMessage } from 'naive-ui'
import { CopyOutline } from '@vicons/ionicons5'
import HeatmapChart from './HeatmapChart.vue'
import { getTaskScheduleConstraints, rescheduleTask, type Task, type TaskScheduleWindow } from '../api'
import { renderMarkdown } from './task-process/taskProcessUtils'
import { parseUtcDate } from '../utils/datetime'
import { buildScheduleTimeDisabled } from '../utils/scheduleWindow'
import { extractSlotErrorMessage } from '../utils/slotError'
import { useBreakpoints } from '../composables/useBreakpoints'
import { useTaskScheduleContext } from '../features/tasks/useTaskScheduleContext'

const props = withDefaults(defineProps<{
  show: boolean
  task?: Task
  hideSummary?: boolean
}>(), {
  task: undefined,
  hideSummary: false,
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  'rescheduled': [task: Task]
}>()

const { t } = useI18n()
const message = useMessage()
const { isMobile } = useBreakpoints()

const localShow = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val),
})

const scheduleDatetime = ref<number | null>(null)
const loading = ref(false)
const scheduleWindow = ref<TaskScheduleWindow | null>(null)
const {
  scheduledTasks,
  scheduledTasksLoading,
  slotMaxTasks,
  slotEnforce,
  slotConfigLoadFailed,
  loadScheduleContext,
} = useTaskScheduleContext()

const renderedPrompt = computed(() => renderMarkdown(props.task?.user_prompt ?? ''))

function copyPromptSource() {
  navigator.clipboard.writeText(props.task?.user_prompt ?? '')
  message.success(t('taskView.copied'))
}

function startOfDay(ts: number): number {
  const d = new Date(ts)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

function endOfDay(ts: number): number {
  return startOfDay(ts) + 24 * 60 * 60 * 1000 - 1
}

const scheduleConstraintHint = computed(() => {
  const window = scheduleWindow.value
  if (!window || window.has_valid_window === false) {
    return window?.has_valid_window === false
      ? t('scheduleConflict.noValidWindow')
      : null
  }
  if (window.min_scheduled_at && window.max_scheduled_at) {
    return t('taskView.rescheduleConstraintWindow', {
      min: formatConstraintTime(window.min_scheduled_at),
      max: formatConstraintTime(window.max_scheduled_at),
    })
  }
  if (window.min_scheduled_at && window.min_source_task_id != null) {
    return t('taskView.rescheduleConstraintFloor', { source: window.min_source_task_id })
  }
  if (window.max_scheduled_at && window.max_source_task_id != null) {
    return t('taskView.rescheduleConstraintCeiling', { source: window.max_source_task_id })
  }
  return null
})

function formatConstraintTime(value: string): string {
  try {
    const d = parseUtcDate(value)
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
  } catch {
    return value
  }
}

function isDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  if (candidate.getTime() < today.getTime()) return true
  const window = scheduleWindow.value
  if (!window) return false
  if (window.has_valid_window === false) return true
  const dayStart = startOfDay(timestamp)
  const dayEnd = endOfDay(timestamp)
  if (window.min_scheduled_at) {
    const min = parseUtcDate(window.min_scheduled_at).getTime()
    if (dayEnd < min) return true
  }
  if (window.max_scheduled_at) {
    const max = parseUtcDate(window.max_scheduled_at).getTime()
    if (dayStart > max) return true
  }
  return false
}

const isTimeDisabled = computed(() => buildScheduleTimeDisabled(scheduleWindow.value))

watch(() => props.show, async (val) => {
  if (!val) return
  scheduleDatetime.value = props.task?.scheduled_at
    ? parseUtcDate(props.task.scheduled_at).getTime()
    : null
  scheduleWindow.value = null
  if (props.task) {
    try {
      scheduleWindow.value = await getTaskScheduleConstraints({ task_id: props.task.id })
    } catch {
      scheduleWindow.value = null
    }
  }
  await loadScheduleContext(true)
  if (slotConfigLoadFailed.value) {
    console.warn('[RescheduleDrawer] Failed to load slot config; heatmap capacity limits may be inaccurate')
  }
})

async function handleSubmit() {
  if (!props.task) return
  if (!scheduleDatetime.value) {
    message.warning(t('taskView.selectRescheduleTime'))
    return
  }
  if (scheduleDatetime.value <= Date.now()) {
    message.warning(t('taskView.rescheduleTimeFuture'))
    return
  }
  loading.value = true
  try {
    const updated = await rescheduleTask(props.task.id, {
      scheduled_datetime: new Date(scheduleDatetime.value).toISOString()
    })
    message.success(t('taskView.taskRescheduled'))
    emit('rescheduled', updated)
    emit('update:show', false)
  } catch (error: any) {
    message.error(extractSlotErrorMessage(error, t, 'taskView.failedToRescheduleTask'))
  } finally {
    loading.value = false
  }
}

function handleHeatmapCellClick(startMs: number) {
  scheduleDatetime.value = startMs
}
</script>

<style scoped>
.reschedule-drawer__summary {
  margin-bottom: 20px;
  padding: 12px 14px;
  background: rgba(15, 23, 42, 0.035);
  border-radius: 8px;
}

.reschedule-drawer__summary-title-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 6px;
}
.reschedule-drawer__summary-title {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
}

.reschedule-drawer__summary-prompt {
  font-size: 13px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.82);
  max-height: 120px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.reschedule-drawer__schedule-preview {
  margin-top: 8px;
}

.reschedule-drawer__hint {
  margin: 0 0 10px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
}

.reschedule-drawer__constraint {
  margin: 0 0 10px;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(32, 128, 240, 0.06);
  color: rgba(29, 78, 216, 0.9);
  font-size: 12px;
  line-height: 1.45;
}

.reschedule-drawer__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
