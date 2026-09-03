import type { ComputedRef, Ref } from 'vue'

import {
  getTaskContainerLogs,
  streamTaskLogs,
  type Task,
  type TaskLog,
} from '../../api'

export const RAW_LOG_WINDOW_MAX_CHARS = 500_000

export function isActiveTaskStatus(status?: string | null): boolean {
  return status === 'running' || status === 'pending' || status === 'queued'
}

interface TaskLogStreamOptions {
  taskId: ComputedRef<number>
  task: Ref<Task | null>
  taskLogs: Ref<TaskLog[]>
  containerLogs: Ref<string>
  containerLogsTruncated: Ref<boolean>
  containerLogsLoading: Ref<boolean>
  translate: (key: string) => string
  onStructuredDone: () => void
  onRawDone: () => void
}

function boundRawLogWindow(text: string): { text: string, truncated: boolean } {
  if (text.length <= RAW_LOG_WINDOW_MAX_CHARS) return { text, truncated: false }
  return {
    text: text.slice(-RAW_LOG_WINDOW_MAX_CHARS),
    truncated: true,
  }
}

function appendRawLogWindow(current: string, incoming: string): {
  text: string
  truncated: boolean
} {
  if (!incoming) return { text: current, truncated: false }
  if (incoming.length >= RAW_LOG_WINDOW_MAX_CHARS) {
    return {
      text: incoming.slice(-RAW_LOG_WINDOW_MAX_CHARS),
      truncated: current.length > 0 || incoming.length > RAW_LOG_WINDOW_MAX_CHARS,
    }
  }

  const boundedCurrent = current.length > RAW_LOG_WINDOW_MAX_CHARS
    ? current.slice(-RAW_LOG_WINDOW_MAX_CHARS)
    : current
  const overflow = boundedCurrent.length + incoming.length - RAW_LOG_WINDOW_MAX_CHARS
  if (overflow > 0) {
    return {
      text: boundedCurrent.slice(overflow) + incoming,
      truncated: true,
    }
  }
  return {
    text: boundedCurrent + incoming,
    truncated: current.length > RAW_LOG_WINDOW_MAX_CHARS,
  }
}

export function useTaskLogStreams(options: TaskLogStreamOptions) {
  let rawLogSource: EventSource | null = null
  let rawLogTaskId: number | null = null
  let rawLogSequenceNo = 0
  let rawLogStreamFinished = false
  let rawLogsFinalized = false
  let rawTabOpen = false
  let rawLogSnapshotRequest = 0
  let rawLogReconnectInFlight = false
  let structuredLogSource: EventSource | null = null
  const pendingStructuredLogs: TaskLog[] = []
  let structuredFlushScheduled = false

  function closeRawLogStream() {
    rawLogSource?.close()
    rawLogSource = null
    rawLogTaskId = null
  }

  function closeStructuredLogStream() {
    structuredLogSource?.close()
    structuredLogSource = null
    pendingStructuredLogs.length = 0
    structuredFlushScheduled = false
  }

  function shouldStreamRawLogs(): boolean {
    const status = options.task.value?.status
    const terminal = status === 'completed' || status === 'failed' || status === 'cancelled'
    return isActiveTaskStatus(status) || (terminal && !rawLogsFinalized)
  }

  function connectStructuredLogStream() {
    if (typeof EventSource === 'undefined') return
    if (!isActiveTaskStatus(options.task.value?.status)) return
    if (structuredLogSource) return

    const sinceId = options.taskLogs.value.length > 0
      ? Math.max(...options.taskLogs.value.map(log => log.id ?? 0))
      : 0

    const mergeLogUpdate = (log: TaskLog) => {
      const index = options.taskLogs.value.findIndex(current => current.id === log.id)
      if (index === -1) return
      const updated = [...options.taskLogs.value]
      updated[index] = log
      options.taskLogs.value = updated
    }

    let source: EventSource | null = null
    source = streamTaskLogs(
      options.taskId.value,
      sinceId,
      (log) => {
        pendingStructuredLogs.push(log)
        if (structuredFlushScheduled) return
        structuredFlushScheduled = true
        queueMicrotask(() => {
          structuredFlushScheduled = false
          if (pendingStructuredLogs.length === 0) return
          const incoming = pendingStructuredLogs.splice(0)
          const current = options.taskLogs.value
          const ids = new Set(current.map(log => log.id))
          const additions = incoming.filter(log => !ids.has(log.id))
          if (additions.length > 0) {
            options.taskLogs.value = [...current, ...additions]
          }
          incoming.filter(log => ids.has(log.id)).forEach(mergeLogUpdate)
        })
      },
      () => {
        if (structuredLogSource !== source) return
        closeStructuredLogStream()
        options.onStructuredDone()
      },
      mergeLogUpdate,
    )
    structuredLogSource = source

    source.onerror = () => {
      if (structuredLogSource !== source) return
      closeStructuredLogStream()
    }
  }

  function connectRawLogStream() {
    if (typeof EventSource === 'undefined') return

    const containerId = options.task.value?.container_id
    if (!containerId || !shouldStreamRawLogs()) {
      closeRawLogStream()
      return
    }

    const currentTaskId = options.taskId.value
    if (rawLogSource && rawLogTaskId === currentTaskId) return
    if (rawLogStreamFinished) return

    closeRawLogStream()
    options.containerLogsLoading.value = !options.containerLogs.value
    rawLogTaskId = currentTaskId
    const source = new EventSource(
      `/api/tasks/${currentTaskId}/raw-log-stream?since_sequence_no=${rawLogSequenceNo}`
    )
    rawLogSource = source

    source.addEventListener('batch', (event) => {
      if (rawLogSource !== source || options.taskId.value !== currentTaskId) return
      let chunks: Array<{ sequence_no: number, content: string, truncated?: boolean }>
      try {
        chunks = JSON.parse((event as MessageEvent).data)
      } catch {
        if (rawLogSource === source) closeRawLogStream()
        options.containerLogsLoading.value = false
        return
      }
      let nextLogs = options.containerLogs.value
      let truncated = options.containerLogsTruncated.value
      for (const chunk of chunks) {
        if (chunk.sequence_no <= rawLogSequenceNo) continue
        rawLogSequenceNo = chunk.sequence_no
        truncated = truncated || Boolean(chunk.truncated)
        const nextWindow = appendRawLogWindow(nextLogs, chunk.content)
        nextLogs = nextWindow.text
        truncated = truncated || nextWindow.truncated
      }
      options.containerLogs.value = nextLogs
      options.containerLogsTruncated.value = truncated
      options.containerLogsLoading.value = false
    })

    source.addEventListener('done', () => {
      if (rawLogSource !== source) return
      rawLogStreamFinished = true
      rawLogsFinalized = true
      closeRawLogStream()
      options.containerLogsLoading.value = false
      void fetchRawLogSnapshot()
      options.onRawDone()
    })

    source.onerror = () => {
      if (rawLogSource !== source) return
      options.containerLogsLoading.value = false
      closeRawLogStream()
    }
  }

  async function fetchRawLogSnapshot(showLoading = false): Promise<boolean> {
    const requestId = ++rawLogSnapshotRequest
    const requestedTaskId = options.taskId.value
    if (showLoading) options.containerLogsLoading.value = true
    try {
      const result = await getTaskContainerLogs(
        requestedTaskId,
        'db',
        RAW_LOG_WINDOW_MAX_CHARS,
      )
      if (requestId === rawLogSnapshotRequest && requestedTaskId === options.taskId.value) {
        const bounded = boundRawLogWindow(result.logs)
        options.containerLogs.value = bounded.text
        options.containerLogsTruncated.value = Boolean(result.logs_truncated) || bounded.truncated
        rawLogSequenceNo = result.last_sequence_no ?? 0
        rawLogsFinalized = result.raw_logs_finalized ?? false
        return true
      }
    } catch {
      if (requestId === rawLogSnapshotRequest && requestedTaskId === options.taskId.value) {
        if (showLoading || !options.containerLogs.value) {
          options.containerLogs.value = options.translate('taskView.failedToFetchContainerLogs')
          options.containerLogsTruncated.value = false
        }
      }
    } finally {
      if (requestId === rawLogSnapshotRequest && showLoading) {
        options.containerLogsLoading.value = false
      }
    }
    return false
  }

  async function reconnectRawLogStream(showLoading = false) {
    if (rawLogReconnectInFlight || rawLogStreamFinished) return
    if (!rawTabOpen || !shouldStreamRawLogs()) return

    rawLogReconnectInFlight = true
    const requestedTaskId = options.taskId.value
    closeRawLogStream()
    try {
      const snapshotLoaded = await fetchRawLogSnapshot(showLoading)
      if (
        snapshotLoaded
        && rawTabOpen
        && requestedTaskId === options.taskId.value
        && shouldStreamRawLogs()
      ) {
        connectRawLogStream()
      }
    } finally {
      rawLogReconnectInFlight = false
    }
  }

  async function openRawLogTab() {
    rawTabOpen = true
    if (isActiveTaskStatus(options.task.value?.status)) {
      await reconnectRawLogStream(true)
      return
    }
    const snapshotLoaded = await fetchRawLogSnapshot(true)
    if (snapshotLoaded && shouldStreamRawLogs()) connectRawLogStream()
  }

  function closeRawLogTab() {
    rawTabOpen = false
    closeRawLogStream()
  }

  function resetLogStreams() {
    rawLogSequenceNo = 0
    rawLogStreamFinished = false
    rawLogsFinalized = false
    options.containerLogsTruncated.value = false
    rawLogSnapshotRequest += 1
    closeStructuredLogStream()
    closeRawLogStream()
  }

  function hasRawLogStream() {
    return rawLogSource !== null
  }

  function hasStructuredLogStream() {
    return structuredLogSource !== null
  }

  function isRawLogTabOpen() {
    return rawTabOpen
  }

  return {
    closeLogStream: closeRawLogStream,
    closeStructuredLogStream,
    shouldStreamRawLogs,
    connectStructuredLogStream,
    connectLogStream: connectRawLogStream,
    fetchRawLogSnapshot,
    reconnectLogStream: reconnectRawLogStream,
    onRawTabOpen: openRawLogTab,
    onRawTabClose: closeRawLogTab,
    resetLogStreams,
    hasRawLogStream,
    hasStructuredLogStream,
    isRawLogTabOpen,
  }
}
