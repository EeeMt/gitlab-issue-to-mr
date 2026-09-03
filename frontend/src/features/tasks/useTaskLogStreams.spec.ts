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
  doneCallback: (() => void) | undefined

  close() {
    this.closed = true
  }

  emitError() {
    this.onerror?.(new Event('error'))
  }

  emitDone() {
    this.doneCallback?.()
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
    mockStreamTaskLogs.mockImplementation((_id, _sinceId, _onLog, onDone) => {
      const source = new FakeEventSource()
      source.doneCallback = onDone
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
})
