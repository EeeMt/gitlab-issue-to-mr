import { ref, type Ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'

import {
  createTask,
  updateTask,
  type Task,
} from '../../api'
import { extractSlotErrorMessage } from '../../utils/slotError'
import {
  isUsageLimitExceededDetail,
  type UsageLimitExceededDetail,
} from '../../utils/usageLimits'
import {
  buildCreateTaskRequest,
  buildUpdateTaskRequest,
  type TaskMode,
  type TaskScheduleType,
} from './taskFormModel'

interface TaskFormSubmissionOptions {
  issueId: Readonly<Ref<number | undefined>>
  task: Readonly<Ref<Task | undefined>>
  prompt: Ref<string>
  priority: Ref<number>
  requireChanges: Ref<boolean>
  taskMode: Ref<TaskMode | null>
  startFreshSession: Ref<boolean>
  taskModeErrorVisible: Ref<boolean>
  selectedProviderId: Ref<number | null>
  harnessKey: Ref<string | null>
  scheduleType: Ref<TaskScheduleType>
  scheduledAt: Ref<number | null>
  runInstructionTemplate: Ref<string>
  initialRunInstructionTemplate: Ref<string>
  runInstructionDirty: Ref<boolean>
  inheritProfileSkills: Ref<boolean>
  selectedSkillIds: Ref<number[]>
  skillSelectionDirty: Ref<boolean>
  submissionBlocked?: Readonly<Ref<boolean>>
  defaultsError: Readonly<Ref<string>>
  getDefaultRunInstructionTemplate: (mode: Exclude<TaskMode, 'freeform'>) => string
  clearScheduledTasks: () => void
  close: () => void
  created: (task: Task) => void
  updated: (task: Task) => void
}

export function useTaskFormSubmission(options: TaskFormSubmissionOptions) {
  const { t } = useI18n()
  const message = useMessage()
  const submitLoading = ref(false)
  const usageLimitDetail = ref<UsageLimitExceededDetail | null>(null)

  function buildTaskCreatedMessage(task: Task): string {
    const sequence = task.issue_sequence
    const position = task.queue_position
    if (sequence != null && position != null) {
      return position === 1
        ? t('issue.taskCreatedQueueHead', { sequence })
        : t('issue.taskCreatedQueued', { sequence, position })
    }
    if (sequence != null) {
      return t('issue.taskCreatedTurn', { sequence })
    }
    return t('issue.taskCreated')
  }

  async function handleCreate() {
    if (options.submissionBlocked?.value) {
      message.warning(t('createTask.harnessCatalogUnavailable'))
      return
    }
    const taskMode = options.taskMode.value
    if (taskMode === null) {
      options.taskModeErrorVisible.value = true
      message.warning(t('issue.pleaseSelectTaskMode'))
      return
    }
    if (taskMode !== 'freeform') {
      if (!options.runInstructionTemplate.value) {
        options.runInstructionTemplate.value = options.getDefaultRunInstructionTemplate(taskMode)
      }
      if (!options.runInstructionTemplate.value.trim()) {
        message.warning(options.defaultsError.value || t('runInstruction.defaultsLoadFailed'))
        return
      }
    }
    if (options.scheduleType.value === 'scheduled') {
      if (!options.scheduledAt.value) {
        message.warning(t('createTask.pleaseSelectScheduledTime'))
        return
      }
      if (options.scheduledAt.value <= Date.now()) {
        message.warning(t('createTask.scheduledTimeFuture'))
        return
      }
    }

    submitLoading.value = true
    usageLimitDetail.value = null
    try {
      const request = buildCreateTaskRequest(options.issueId.value!, {
        prompt: options.prompt.value,
        priority: options.priority.value,
        requireChanges: options.requireChanges.value,
        taskMode,
        sessionMode: options.startFreshSession.value ? 'fresh' : 'continue',
        harnessKey: options.harnessKey?.value ?? null,
        selectedProviderId: options.selectedProviderId.value,
        scheduleType: options.scheduleType.value,
        scheduledAt: options.scheduledAt.value,
        runInstructionTemplate: options.runInstructionTemplate.value,
        runInstructionDirty: options.runInstructionDirty.value,
        inheritProfileSkills: options.inheritProfileSkills.value,
        selectedSkillIds: options.selectedSkillIds.value,
        skillSelectionDirty: options.skillSelectionDirty.value,
      })
      const created = await createTask(request)
      message.success(buildTaskCreatedMessage(created))
      options.prompt.value = ''
      options.scheduledAt.value = null
      options.selectedProviderId.value = null
      options.startFreshSession.value = false
      options.scheduleType.value = 'now'
      options.inheritProfileSkills.value = true
      options.selectedSkillIds.value = []
      options.skillSelectionDirty.value = false
      options.clearScheduledTasks()
      options.close()
      options.created(created)
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail
      if (isUsageLimitExceededDetail(detail)) {
        usageLimitDetail.value = detail
      } else {
        message.error(extractSlotErrorMessage(error, t, 'createTask.failedToCreateTask'))
      }
    } finally {
      submitLoading.value = false
    }
  }

  async function handleEdit() {
    if (options.submissionBlocked?.value) {
      message.warning(t('createTask.harnessCatalogUnavailable'))
      return
    }
    const original = options.task.value
    if (!original) return

    const prompt = options.prompt.value.trim()
    if (!prompt) {
      message.warning(t('createTask.pleaseEnterPrompt'))
      return
    }
    const request = buildUpdateTaskRequest(original, {
      prompt,
      priority: options.priority.value,
      requireChanges: options.requireChanges.value,
      taskMode: options.taskMode.value ?? 'execute',
      sessionMode: 'continue',
      harnessKey: null,
      selectedProviderId: options.selectedProviderId.value,
      runInstructionTemplate: options.runInstructionTemplate.value,
      runInstructionDirty: options.runInstructionDirty.value,
      inheritProfileSkills: options.inheritProfileSkills.value,
      selectedSkillIds: options.selectedSkillIds.value,
      skillSelectionDirty: options.skillSelectionDirty.value,
    }, options.initialRunInstructionTemplate.value)

    if (Object.keys(request).length === 0) {
      options.close()
      return
    }

    submitLoading.value = true
    try {
      const updated = await updateTask(original.id, request)
      message.success(t('taskView.taskUpdated'))
      options.close()
      options.updated(updated)
    } catch (error: unknown) {
      const detail = (error as { response?: { data?: { detail?: unknown } } })
        .response?.data?.detail
      message.error(
        typeof detail === 'string'
          ? detail
          : t('taskView.failedToUpdateTask'),
      )
    } finally {
      submitLoading.value = false
    }
  }

  return {
    handleCreate,
    handleEdit,
    submitLoading,
    usageLimitDetail,
  }
}
