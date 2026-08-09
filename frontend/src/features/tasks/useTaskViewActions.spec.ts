import { computed, ref } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Task } from '../../api'
import { useTaskViewActions, type TaskArchiveMetadata } from './useTaskViewActions'

const {
  apiMocks,
  messageMocks,
  routerPush,
} = vi.hoisted(() => ({
  apiMocks: {
    cancelTask: vi.fn(),
    downloadTaskArchive: vi.fn(),
    executeTask: vi.fn(),
    overrideTaskStatus: vi.fn(),
    retryTask: vi.fn(),
  },
  messageMocks: {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
  routerPush: vi.fn(),
}))

vi.mock('../../api', () => apiMocks)
vi.mock('naive-ui', () => ({
  useMessage: () => messageMocks,
}))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('vue-router', () => ({
  useRouter: () => ({ push: routerPush }),
}))

function createActions() {
  const taskId = ref(7)
  const task = ref({ id: 7 } as Task)
  const archiveMetadata = ref<TaskArchiveMetadata | null>(null)
  const refreshTask = vi.fn(async () => undefined)
  const resetLogsState = vi.fn()
  const checkActiveRetry = vi.fn(async () => undefined)
  const loadScheduleContext = vi.fn(async () => undefined)
  const actions = useTaskViewActions({
    taskId: computed(() => taskId.value),
    task,
    archiveMetadata,
    refreshTask,
    resetLogsState,
    checkActiveRetry,
    loadScheduleContext,
  })
  return {
    actions,
    archiveMetadata,
    checkActiveRetry,
    loadScheduleContext,
    refreshTask,
    resetLogsState,
    taskId,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((resolvePromise, rejectPromise) => {
    resolve = resolvePromise
    reject = rejectPromise
  })
  return { promise, reject, resolve }
}

describe('useTaskViewActions', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.cancelTask.mockResolvedValue(undefined)
    apiMocks.executeTask.mockResolvedValue(undefined)
    apiMocks.overrideTaskStatus.mockResolvedValue(undefined)
    routerPush.mockResolvedValue(undefined)
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:task-archive'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })
  })

  it('cancels the current task and refreshes its state', async () => {
    const { actions, refreshTask } = createActions()

    await actions.handleCancel()

    expect(apiMocks.cancelTask).toHaveBeenCalledWith(7)
    expect(refreshTask).toHaveBeenCalledOnce()
    expect(messageMocks.success).toHaveBeenCalledWith('taskView.taskCancelled')
  })

  it('keeps retry conflict handling inside the action boundary', async () => {
    apiMocks.retryTask.mockRejectedValue({ response: { status: 409 } })
    const { actions, checkActiveRetry } = createActions()

    await actions.handleRetry()

    expect(checkActiveRetry).toHaveBeenCalledOnce()
    expect(messageMocks.warning).toHaveBeenCalledWith('taskView.retryAlreadyExists')
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('surfaces retry_lineage_conflict as a fresh-session confirm instead of a generic 409', async () => {
    apiMocks.retryTask.mockRejectedValue({
      response: {
        status: 409,
        data: {
          detail: {
            code: 'retry_lineage_conflict',
            message: 'Retry source belongs to an older session lineage',
            source_lineage: { harness_key: 'claude', session_namespace: 'claude-old', generation: 1, reset_task_id: 70 },
            tail_lineage: { harness_key: 'codex', session_namespace: 'codex-new', generation: 2, reset_task_id: 80 },
            allowed_actions: ['fresh_retry'],
          },
        },
      },
    })
    const { actions } = createActions()

    await actions.handleRetry()

    expect(actions.showFreshRetryConfirm.value).toBe(true)
    expect(actions.freshRetrySourceLineage.value?.harness_key).toBe('claude')
    expect(actions.freshRetryTailLineage.value?.generation).toBe(2)
    expect(messageMocks.warning).not.toHaveBeenCalledWith('taskView.retryAlreadyExists')
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('confirmFreshRetry resubmits with lineage_strategy=fresh_retry and navigates', async () => {
    apiMocks.retryTask.mockResolvedValue({ id: 72 } as Task)
    apiMocks.retryTask.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: 'retry_lineage_conflict',
            source_lineage: { harness_key: 'claude', session_namespace: 'claude-old', generation: 1, reset_task_id: 70 },
            tail_lineage: { harness_key: 'codex', session_namespace: 'codex-new', generation: 2, reset_task_id: 80 },
            allowed_actions: ['fresh_retry'],
          },
        },
      },
    })
    const { actions } = createActions()

    await actions.handleRetry()
    expect(actions.showFreshRetryConfirm.value).toBe(true)

    await actions.confirmFreshRetry()

    expect(apiMocks.retryTask).toHaveBeenLastCalledWith(7, undefined, 'fresh_retry')
    expect(routerPush).toHaveBeenCalledWith('/tasks/72')
    expect(actions.showFreshRetryConfirm.value).toBe(false)
  })

  it('confirmFreshRetry preserves the chosen schedule when retrying fresh', async () => {
    apiMocks.retryTask.mockResolvedValue({ id: 73 } as Task)
    apiMocks.retryTask.mockRejectedValueOnce({
      response: {
        status: 409,
        data: {
          detail: {
            code: 'retry_lineage_conflict',
            source_lineage: { harness_key: 'claude', session_namespace: 'claude-old', generation: 1, reset_task_id: 70 },
            tail_lineage: { harness_key: 'codex', session_namespace: 'codex-new', generation: 2, reset_task_id: 80 },
            allowed_actions: ['fresh_retry'],
          },
        },
      },
    })
    const { actions } = createActions()
    const scheduledAt = Date.now() + 60_000
    actions.retryScheduleDatetime.value = scheduledAt

    await actions.handleRetryWithSchedule()
    expect(actions.showFreshRetryConfirm.value).toBe(true)

    await actions.confirmFreshRetry()

    expect(apiMocks.retryTask).toHaveBeenLastCalledWith(7, new Date(scheduledAt).toISOString(), 'fresh_retry')
    expect(routerPush).toHaveBeenCalledWith('/tasks/73')
  })

  it('does not reset or redirect the next task when retry completes after navigation', async () => {
    const retryResult = deferred<Task>()
    apiMocks.retryTask.mockReturnValueOnce(retryResult.promise)
    const { actions, resetLogsState, taskId } = createActions()

    const request = actions.handleRetry()
    taskId.value = 8
    retryResult.resolve({ id: 70 } as Task)
    await request

    expect(apiMocks.retryTask).toHaveBeenCalledWith(7)
    expect(resetLogsState).not.toHaveBeenCalled()
    expect(messageMocks.success).not.toHaveBeenCalled()
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('rejects a scheduled retry in the past before calling the API', async () => {
    const { actions } = createActions()
    actions.retryScheduleDatetime.value = Date.now() - 1

    await actions.handleRetryWithSchedule()

    expect(apiMocks.retryTask).not.toHaveBeenCalled()
    expect(messageMocks.error).toHaveBeenCalledWith('taskView.rescheduleTimeFuture')
  })

  it('does not redirect the next task when a scheduled retry completes after navigation', async () => {
    const retryResult = deferred<Task>()
    apiMocks.retryTask.mockReturnValueOnce(retryResult.promise)
    const { actions, resetLogsState, taskId } = createActions()
    const scheduledAt = Date.now() + 60_000
    actions.retryScheduleDatetime.value = scheduledAt

    const request = actions.handleRetryWithSchedule()
    taskId.value = 8
    retryResult.resolve({ id: 71 } as Task)
    await request

    expect(apiMocks.retryTask).toHaveBeenCalledWith(7, new Date(scheduledAt).toISOString())
    expect(resetLogsState).not.toHaveBeenCalled()
    expect(routerPush).not.toHaveBeenCalled()
  })

  it('uses the captured archive name when metadata changes during download', async () => {
    const downloadResult = deferred<Blob>()
    apiMocks.downloadTaskArchive.mockReturnValueOnce(downloadResult.promise)
    const { actions, archiveMetadata, taskId } = createActions()
    const clickedDownloads: string[] = []
    vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (
      this: HTMLAnchorElement,
    ) {
      clickedDownloads.push(this.download)
    })
    archiveMetadata.value = {
      archive_name: 'task-7-runtime.tar.gz',
      archive_size_bytes: 128,
      created_at: '2026-07-05T10:00:00Z',
      file_exists: true,
    }

    const request = actions.handleDownloadArchive()
    taskId.value = 8
    archiveMetadata.value = null
    downloadResult.resolve(new Blob(['archive']))
    await request

    expect(apiMocks.downloadTaskArchive).toHaveBeenCalledWith(7)
    expect(clickedDownloads).toEqual(['task-7-runtime.tar.gz'])
    expect(messageMocks.error).not.toHaveBeenCalled()
  })

  it('loads schedule context when opening the schedule drawer', async () => {
    const { actions, loadScheduleContext } = createActions()

    await actions.openScheduleDrawer()

    expect(actions.showScheduleDrawer.value).toBe(true)
    expect(loadScheduleContext).toHaveBeenCalledWith(true)
  })
})
