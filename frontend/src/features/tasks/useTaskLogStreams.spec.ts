import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest'
import { computed, ref } from 'vue'

const { mockStreamTaskLogs, mockGetTaskContainerLogs, mockSources } = vi.hoisted(() => ({
  mockStreamTaskLogs: vi.fn(),
  mockGetTaskContainerLogs: vi.fn(),
  mockSources: [] as FakeEventSource[],
}))

vi.mock('../../api', () => ({
  getTaskContainerLogs: mockGetTaskContainerLogs,
  streamTaskLogs: mockStreamTaskLogs,
}))

import { useTaskLogStreams } from './useTaskLogStreams'

class FakeEventSource {
  onerror: ((event: Event) => void) | null = null
  closed = false
  logCallback: ((log: any) => void) | undefined
  doneCallback: (() => void) | undefined
  updateCallback: ((log: any) => void) | undefined

  close() {
    this.closed = true
  }

  emitError() {
    this.onerror?.(new Event('error'))
  }

  emitDone() {
    this.doneCallback?.()
  }

  emitLog(log: any) {
    this.logCallback?.(log)
  }

  emitUpdate(log: any) {
    this.updateCallback?.(log)
  }
}

function createStreamState() {
  return {
    taskId: computed(() => 1),
    task: ref({ status: 'running' } as any),
    taskLogs: ref([]),
    containerLogs: ref(''),
    containerLogsTruncated: ref(false),
    containerLogsLoading: ref(false),
    translate: (key: string) => key,
    onStructuredDone: vi.fn(),
    onRawDone: vi.fn(),
  }
}

describe('useTaskLogStreams structured stream lifecycle', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockSources.length = 0
    mockStreamTaskLogs.mockImplementation((_id, _sinceId, onLog, onDone, onUpdate) => {
      const source = new FakeEventSource()
      source.logCallback = onLog
      source.doneCallback = onDone
      source.updateCallback = onUpdate
      mockSources.push(source)
      return source
    })
    vi.stubGlobal('EventSource', FakeEventSource)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('ignores a stale error from a previous source after reconnect', () => {
    const state = createStreamState()
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()
    const first = mockSources[0]
    first.emitError()
    streams.connectStructuredLogStream()
    const second = mockSources[1]

    first.emitError()

    expect(first.closed).toBe(true)
    expect(second.closed).toBe(false)
    expect(streams.hasStructuredLogStream()).toBe(true)
  })

  it('ignores a stale done callback from a previous source after reconnect', () => {
    const state = createStreamState()
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()
    const first = mockSources[0]
    first.emitError()
    streams.connectStructuredLogStream()
    const second = mockSources[1]

    first.emitDone()

    expect(second.closed).toBe(false)
    expect(streams.hasStructuredLogStream()).toBe(true)
    expect(state.onStructuredDone).not.toHaveBeenCalled()
  })

  it('ignores stale batch and update callbacks from a previous source after reconnect', async () => {
    const state = createStreamState()
    state.taskLogs.value = [{ id: 7, message: 'current' }] as any
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()
    const first = mockSources[0]
    first.emitError()
    streams.connectStructuredLogStream()
    const second = mockSources[1]

    first.emitLog({ id: 8, message: 'stale batch' })
    first.emitUpdate({ id: 7, message: 'stale update' })
    await Promise.resolve()

    expect(state.taskLogs.value).toEqual([{ id: 7, message: 'current' }])
    expect(second.closed).toBe(false)
    expect(streams.hasStructuredLogStream()).toBe(true)
  })
})
