<template>
  <n-drawer v-model:show="localShow" :width="isMobile ? '100%' : 680" placement="right">
    <n-drawer-content :title="t('taskView.rescheduleTask')" closable>
      <div class="reschedule-drawer">
        <div v-if="task && !hideSummary" class="reschedule-drawer__summary">
          <div class="reschedule-drawer__summary-title">Task #{{ task.id }}</div>
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
            />
          </n-form-item>
        </n-form>

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
import { NDrawer, NDrawerContent, NButton, NSpin, NForm, NFormItem, NDatePicker, useMessage } from 'naive-ui'
import HeatmapChart from './HeatmapChart.vue'
import { rescheduleTask, getScheduledTasks, getConfig, type Task } from '../api'
import { renderMarkdown } from './task-process/taskProcessUtils'
import { parseUtcDate } from '../utils/datetime'
import { extractSlotErrorMessage } from '../utils/slotError'
import { useBreakpoints } from '../composables/useBreakpoints'

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
const scheduledTasks = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)

const renderedPrompt = computed(() => renderMarkdown(props.task?.user_prompt ?? ''))

function isDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

watch(() => props.show, async (val) => {
  if (!val) return
  scheduleDatetime.value = props.task?.scheduled_at
    ? parseUtcDate(props.task.scheduled_at).getTime()
    : null
  scheduledTasksLoading.value = true
  try {
    scheduledTasks.value = await getScheduledTasks()
  } catch {
    scheduledTasks.value = []
  } finally {
    scheduledTasksLoading.value = false
  }
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
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

.reschedule-drawer__summary-title {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
  margin-bottom: 6px;
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

.reschedule-drawer__footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}
</style>
