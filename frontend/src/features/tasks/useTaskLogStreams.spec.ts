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

import {
  computeStructuredStreamSinceId,
  getThinkingStatus,
  mergeTaskLogState,
  parseLogMetadata,
  useTaskLogStreams,
} from './useTaskLogStreams'

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

  it('requests a rewound since_id when an in-progress thinking row is held', () => {
    const state = createStreamState()
    state.taskLogs.value = [
      { id: 4, log_type: 'thinking', metadata: JSON.stringify({ status: 'completed' }) },
      { id: 6, log_type: 'thinking', metadata: JSON.stringify({ status: 'in_progress' }) },
      { id: 9, log_type: 'tool_call', message: 'call' },
    ] as any
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()

    expect(mockStreamTaskLogs.mock.calls[0][1]).toBe(5)
  })

  it('appends new ids once and updates the same id in place across batch flushes', async () => {
    const state = createStreamState()
    state.taskLogs.value = [{ id: 7, message: 'current' }] as any
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()
    const source = mockSources[0]

    source.emitLog({ id: 8, message: 'first' })
    await Promise.resolve()
    source.emitLog({ id: 8, message: 'second' })
    await Promise.resolve()

    expect(state.taskLogs.value.map(log => log.id)).toEqual([7, 8])
    expect(state.taskLogs.value.find(log => log.id === 8)?.message).toBe('second')
  })

  it('updates a thinking row in place over batch and update paths without regressing', async () => {
    const state = createStreamState()
    const thinkingRow = (id: number, status: string) => ({
      id,
      task_id: 1,
      log_level: 'info',
      log_type: 'thinking',
      message: `thinking ${id}`,
      created_at: '2026-09-04T00:00:00Z',
      metadata: JSON.stringify({ status }),
    })
    state.taskLogs.value = [thinkingRow(9, 'in_progress')] as any
    const streams = useTaskLogStreams(state)

    streams.connectStructuredLogStream()
    const source = mockSources[0]

    // Batch replay carries the completed snapshot; the row upgrades in place.
    source.emitLog(thinkingRow(9, 'completed'))
    await Promise.resolve()
    expect(state.taskLogs.value).toHaveLength(1)
    expect(JSON.parse((state.taskLogs.value[0] as any).metadata).status).toBe('completed')

    // A delayed update with a stale in_progress snapshot must not regress it.
    source.emitUpdate(thinkingRow(9, 'in_progress'))
    expect(state.taskLogs.value).toHaveLength(1)
    expect(JSON.parse((state.taskLogs.value[0] as any).metadata).status).toBe('completed')

    // The update path can complete a fresh in-progress row in place too.
    source.emitUpdate(thinkingRow(10, 'completed'))
    expect(state.taskLogs.value.map(log => log.id)).toEqual([9, 10])
    expect(JSON.parse((state.taskLogs.value[1] as any).metadata).status).toBe('completed')
  })
})

describe('thinking log metadata and merge helpers', () => {
  const thinkingLog = (id: number, status?: string, overrides: Record<string, unknown> = {}) => ({
    id,
    task_id: 1,
    log_level: 'info',
    log_type: 'thinking',
    message: `thinking ${id}`,
    created_at: '2026-09-04T00:00:00Z',
    metadata: status === undefined ? undefined : JSON.stringify({ status }),
    ...overrides,
  })

  it('parseLogMetadata accepts metadata objects as-is', () => {
    expect(parseLogMetadata({ status: 'in_progress', attempt_id: 'a' })).toEqual({
      status: 'in_progress',
      attempt_id: 'a',
    })
  })

  it('parseLogMetadata parses JSON string metadata', () => {
    expect(parseLogMetadata('{"status":"completed"}')).toEqual({ status: 'completed' })
  })

  it('parseLogMetadata tolerates garbage and non-object input', () => {
    expect(parseLogMetadata(null)).toEqual({})
    expect(parseLogMetadata(undefined)).toEqual({})
    expect(parseLogMetadata('not json')).toEqual({})
    expect(parseLogMetadata('{"status":"completed"')).toEqual({})
    expect(parseLogMetadata(42)).toEqual({})
    expect(parseLogMetadata([{ status: 'completed' }])).toEqual({})
  })

  it('getThinkingStatus only reads lifecycle status off thinking rows', () => {
    expect(getThinkingStatus(thinkingLog(1, 'completed') as any)).toBe('completed')
    expect(getThinkingStatus(thinkingLog(2, 'in_progress') as any)).toBe('in_progress')
    expect(getThinkingStatus(thinkingLog(3, 'interrupted') as any)).toBe('interrupted')
    expect(
      getThinkingStatus({ ...thinkingLog(4, 'in_progress'), log_type: 'assistant_text' } as any)
    ).toBeNull()
    expect(
      getThinkingStatus({ ...thinkingLog(5, 'in_progress'), log_type: 'tool_call' } as any)
    ).toBeNull()
    expect(
      getThinkingStatus({ ...thinkingLog(6), metadata: JSON.stringify({ attempt_id: 'a' }) } as any)
    ).toBeNull()
    expect(
      getThinkingStatus({ ...thinkingLog(7), metadata: JSON.stringify({ status: 'bogus' }) } as any)
    ).toBeNull()
  })

  it('computeStructuredStreamSinceId returns 0 with no logs', () => {
    expect(computeStructuredStreamSinceId([])).toBe(0)
  })

  it('computeStructuredStreamSinceId returns the max id when nothing is in progress', () => {
    const logs = [
      thinkingLog(4, 'completed'),
      { id: 9, log_type: 'tool_call', message: 'call' },
    ]
    expect(computeStructuredStreamSinceId(logs as any)).toBe(9)
  })

  it('computeStructuredStreamSinceId rewinds below the earliest in-progress thinking row', () => {
    const logs = [
      thinkingLog(2, 'completed'),
      thinkingLog(5, 'in_progress'),
      { id: 7, log_type: 'tool_call', message: 'call' },
    ]
    expect(computeStructuredStreamSinceId(logs as any)).toBe(4)
  })

  it('computeStructuredStreamSinceId floors the rewind at 0', () => {
    expect(computeStructuredStreamSinceId([thinkingLog(1, 'in_progress')] as any)).toBe(0)
    expect(computeStructuredStreamSinceId([thinkingLog(3, 'in_progress')] as any)).toBe(2)
  })

  it('computeStructuredStreamSinceId ignores in_progress metadata on non-thinking rows', () => {
    const logs = [
      {
        id: 5,
        log_type: 'tool_call',
        message: 'call',
        metadata: JSON.stringify({ status: 'in_progress' }),
      },
    ]
    expect(computeStructuredStreamSinceId(logs as any)).toBe(5)
  })

  it('mergeTaskLogState dedupes by id, preserves order, and appends new ids in arrival order', () => {
    const current = [
      { id: 7, message: 'seven' },
      { id: 3, message: 'three' },
      { id: 9, message: 'nine' },
    ]
    const incoming = [
      { id: 3, message: 'three updated' },
      { id: 5, message: 'five' },
      { id: 7, message: 'seven updated' },
    ]
    const result = mergeTaskLogState(current as any, incoming as any)
    expect(result.map(log => log.id)).toEqual([7, 3, 9, 5])
    expect(result.find(log => log.id === 3)?.message).toBe('three updated')
    expect(result.find(log => log.id === 7)?.message).toBe('seven updated')
  })

  it('mergeTaskLogState never regresses a completed row to in_progress', () => {
    const current = [thinkingLog(1, 'completed')]
    const result = mergeTaskLogState(current as any, [thinkingLog(1, 'in_progress')] as any)
    expect(result).toHaveLength(1)
    expect(JSON.parse((result[0] as any).metadata).status).toBe('completed')
  })

  it('mergeTaskLogState upgrades interrupted and in_progress rows toward completed', () => {
    const interruptedToCompleted = mergeTaskLogState(
      [thinkingLog(1, 'interrupted')] as any,
      [thinkingLog(1, 'completed')] as any,
    )
    expect(JSON.parse((interruptedToCompleted[0] as any).metadata).status).toBe('completed')

    const inProgressToCompleted = mergeTaskLogState(
      [thinkingLog(2, 'in_progress')] as any,
      [thinkingLog(2, 'completed')] as any,
    )
    expect(JSON.parse((inProgressToCompleted[0] as any).metadata).status).toBe('completed')

    const inProgressToInterrupted = mergeTaskLogState(
      [thinkingLog(3, 'in_progress')] as any,
      [thinkingLog(3, 'interrupted')] as any,
    )
    expect(JSON.parse((inProgressToInterrupted[0] as any).metadata).status).toBe('interrupted')
  })

  it('mergeTaskLogState applies duplicates within one incoming batch in arrival order', () => {
    const incoming = [
      thinkingLog(1, 'in_progress'),
      thinkingLog(1, 'completed'),
      thinkingLog(1, 'in_progress'),
    ]
    const result = mergeTaskLogState([], incoming as any)
    expect(result).toHaveLength(1)
    expect(JSON.parse((result[0] as any).metadata).status).toBe('completed')
  })

  it('mergeTaskLogState lets no-status rows replace each other freely', () => {
    const current = [{ id: 1, message: 'old' }]
    const result = mergeTaskLogState(current as any, [{ id: 1, message: 'new' }] as any)
    expect(result).toEqual([{ id: 1, message: 'new' }])
  })

  it('mergeTaskLogState keeps an existing lifecycle row over a no-status snapshot of the same id', () => {
    const current = [thinkingLog(1, 'completed')]
    const result = mergeTaskLogState(current as any, [
      { id: 1, log_type: 'thinking', message: 'legacy static row' },
    ] as any)
    expect(result).toHaveLength(1)
    expect(JSON.parse((result[0] as any).metadata).status).toBe('completed')
  })
})
