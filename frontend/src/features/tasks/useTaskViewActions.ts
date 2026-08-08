import { ref, type ComputedRef, type Ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import {
  cancelTask,
  downloadTaskArchive,
  executeTask,
  overrideTaskStatus,
  retryTask,
  type Task,
} from '../../api'

export interface TaskArchiveMetadata {
  archive_name: string
  archive_size_bytes: number
  created_at: string
  file_exists: boolean
}

interface TaskViewActionsOptions {
  taskId: ComputedRef<number>
  task: Ref<Task | null>
  archiveMetadata: Ref<TaskArchiveMetadata | null>
  refreshTask: () => Promise<void>
  resetLogsState: () => void
  checkActiveRetry: () => Promise<void>
  loadScheduleContext: (force?: boolean) => Promise<void>
}

export function useTaskViewActions(options: TaskViewActionsOptions) {
  const router = useRouter()
  const message = useMessage()
  const { t } = useI18n()

  const actionLoading = ref(false)
  const archiveDownloadLoading = ref(false)
  const retryScheduleDatetime = ref<number | null>(null)
  const showScheduleDrawer = ref(false)
  const showEditDrawer = ref(false)
  const showCreateDrawer = ref(false)
  const showRescheduleDrawer = ref(false)
  const showOverrideModal = ref(false)
  const overrideTargetStatus = ref<'completed' | 'failed' | null>(null)
  const overrideReason = ref('')
  const overrideLoading = ref(false)

  function isCurrentTask(taskId: number): boolean {
    return options.taskId.value === taskId
  }

  function openOverrideModal(targetStatus: 'completed' | 'failed') {
    overrideTargetStatus.value = targetStatus
    overrideReason.value = ''
    showOverrideModal.value = true
  }

  async function confirmOverride() {
    if (!overrideTargetStatus.value || !options.task.value) return
    const requestedTaskId = options.task.value.id
    const targetStatus = overrideTargetStatus.value
    const reason = overrideReason.value || undefined
    overrideLoading.value = true
    try {
      await overrideTaskStatus(requestedTaskId, targetStatus, reason)
      if (!isCurrentTask(requestedTaskId)) return
      showOverrideModal.value = false
      await options.refreshTask()
    } catch {
      if (isCurrentTask(requestedTaskId)) {
        message.error(t('taskView.failedToOverrideStatus'))
      }
    } finally {
      overrideLoading.value = false
    }
  }

  async function handleCancel() {
    const requestedTaskId = options.taskId.value
    actionLoading.value = true
    try {
      await cancelTask(requestedTaskId)
      if (!isCurrentTask(requestedTaskId)) return
      message.success(t('taskView.taskCancelled'))
      void options.refreshTask()
    } catch {
      if (isCurrentTask(requestedTaskId)) {
        message.error(t('taskView.failedToCancelTask'))
      }
    } finally {
      actionLoading.value = false
    }
  }

  async function handleDownloadArchive() {
    const metadata = options.archiveMetadata.value
    if (!metadata?.file_exists) return
    const requestedTaskId = options.taskId.value
    const archiveName = metadata.archive_name
    archiveDownloadLoading.value = true
    try {
      const blob = await downloadTaskArchive(requestedTaskId)
      const url = URL.createObjectURL(blob)
      try {
        const anchor = document.createElement('a')
        anchor.href = url
        anchor.download = archiveName
        document.body.appendChild(anchor)
        anchor.click()
        anchor.remove()
      } finally {
        URL.revokeObjectURL(url)
      }
    } catch {
      if (isCurrentTask(requestedTaskId)) {
        message.error(t('taskView.failedToDownloadRuntimeArchive'))
      }
    } finally {
      archiveDownloadLoading.value = false
    }
  }

  async function handleRetry() {
    const requestedTaskId = options.taskId.value
    actionLoading.value = true
    try {
      const newTask = await retryTask(requestedTaskId)
      if (!isCurrentTask(requestedTaskId)) return
      options.resetLogsState()
      message.success(t('taskView.taskRetryScheduled'))
      void router.push(`/tasks/${newTask.id}`)
    } catch (error: any) {
      if (!isCurrentTask(requestedTaskId)) return
      if (error?.response?.status === 409) {
        message.warning(t('taskView.retryAlreadyExists'))
        await options.checkActiveRetry()
      } else {
        message.error(t('taskView.failedToRetryTask'))
      }
    } finally {
      actionLoading.value = false
    }
  }

  async function handleRetryWithSchedule() {
    if (!retryScheduleDatetime.value) {
      message.error(t('taskView.selectRescheduleTime'))
      return
    }
    if (retryScheduleDatetime.value <= Date.now()) {
      message.error(t('taskView.rescheduleTimeFuture'))
      return
    }
    const requestedTaskId = options.taskId.value
    const scheduledDatetime = retryScheduleDatetime.value
    actionLoading.value = true
    try {
      const newTask = await retryTask(
        requestedTaskId,
        new Date(scheduledDatetime).toISOString(),
      )
      if (!isCurrentTask(requestedTaskId)) return
      retryScheduleDatetime.value = null
      showScheduleDrawer.value = false
      options.resetLogsState()
      message.success(t('taskView.taskRetryRescheduled'))
      void router.push(`/tasks/${newTask.id}`)
    } catch (error: any) {
      if (!isCurrentTask(requestedTaskId)) return
      if (error?.response?.status === 409) {
        message.warning(t('taskView.retryAlreadyExists'))
        await options.checkActiveRetry()
      } else {
        message.error(t('taskView.failedToRetryTask'))
      }
    } finally {
      actionLoading.value = false
    }
  }

  async function handleExecute() {
    const requestedTaskId = options.taskId.value
    actionLoading.value = true
    try {
      const result = await executeTask(requestedTaskId)
      if (!isCurrentTask(requestedTaskId)) return
      if (result.queue_position && result.queue_position > 1) {
        message.warning(t('taskView.taskWillRunAfterPredecessors', {
          position: result.queue_position,
          blockedBy: result.blocked_by_task_id ?? '',
        }))
      } else {
        message.success(t('taskView.taskExecutionStarted'))
      }
      void options.refreshTask()
    } catch {
      if (isCurrentTask(requestedTaskId)) {
        message.error(t('taskView.failedToExecuteTask'))
      }
    } finally {
      actionLoading.value = false
    }
  }

  async function openScheduleDrawer() {
    showScheduleDrawer.value = true
    await options.loadScheduleContext(true)
  }

  function handleScheduleHeatmapCellClick(startMs: number) {
    retryScheduleDatetime.value = startMs
  }

  function handleAppendTaskCreated(created: Task) {
    showCreateDrawer.value = false
    void router.push(`/tasks/${created.id}`)
  }

  return {
    actionLoading,
    archiveDownloadLoading,
    confirmOverride,
    handleAppendTaskCreated,
    handleCancel,
    handleDownloadArchive,
    handleExecute,
    handleRetry,
    handleRetryWithSchedule,
    handleScheduleHeatmapCellClick,
    openOverrideModal,
    openScheduleDrawer,
    overrideLoading,
    overrideReason,
    overrideTargetStatus,
    retryScheduleDatetime,
    showCreateDrawer,
    showEditDrawer,
    showOverrideModal,
    showRescheduleDrawer,
    showScheduleDrawer,
  }
}
