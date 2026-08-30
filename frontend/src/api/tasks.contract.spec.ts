import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGet, mockPost, mockPatch, mockPut } = vi.hoisted(() => ({
  mockGet: vi.fn(),
  mockPost: vi.fn(),
  mockPatch: vi.fn(),
  mockPut: vi.fn(),
}))

vi.mock('./client', () => ({
  api: {
    get: mockGet,
    post: mockPost,
    patch: mockPatch,
    put: mockPut,
  }
}))

import {
  createTask,
  getRunInstructionTemplateDefaults,
  getSlotCapacity,
  getTaskArchive,
  previewRunInstructionTemplate,
  retryTask,
  sendHarnessCommand,
  streamTaskLogs,
  updateTask,
  type CreateTaskRequest,
  type RunInstructionTemplateDefaults,
  type RunInstructionTemplatePreviewRequest,
  type Task,
  type TaskLog,
  type TaskMode,
  type UpdateTaskRequest,
} from './tasks'
import { createMockTask } from '../test/mocks/api'

class FakeEventSource {
  static latest: FakeEventSource | null = null

  readonly url: string
  readonly listeners = new Map<string, (event: MessageEvent) => void>()
  onmessage: ((event: MessageEvent) => void) | null = null
  onerror: ((event: Event) => void) | null = null
  closed = false

  constructor(url: string) {
    this.url = url
    FakeEventSource.latest = this
  }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject) {
    this.listeners.set(type, listener as (event: MessageEvent) => void)
  }

  emit(type: string, data = '') {
    this.listeners.get(type)?.({ data } as MessageEvent)
  }

  close() {
    this.closed = true
  }
}

describe('task API boundary contract', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    vi.stubGlobal('EventSource', FakeEventSource)
    FakeEventSource.latest = null
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('preserves create, update, retry, capacity and archive HTTP contracts', async () => {
    mockPost.mockResolvedValue({ data: { id: 12 } })
    mockPatch.mockResolvedValue({ data: { id: 12 } })
    mockGet.mockResolvedValue({ data: { file_exists: true } })

    const createPayload = {
      issue_id: 7,
      task_mode: 'execute' as const,
      require_changes: false,
    }
    await createTask(createPayload)
    await updateTask(12, { priority: 0, require_changes: true })
    await retryTask(12, '2026-07-05T10:00:00.000Z')
    await getSlotCapacity('2026-07-05T10:00:00.000Z')
    await getTaskArchive(12)

    expect(mockPost).toHaveBeenNthCalledWith(1, '/tasks', createPayload)
    expect(mockPatch).toHaveBeenCalledWith(
      '/tasks/12',
      { priority: 0, require_changes: true }
    )
    expect(mockPost).toHaveBeenNthCalledWith(
      2,
      '/tasks/12/retry',
      { scheduled_datetime: '2026-07-05T10:00:00.000Z' }
    )
    expect(mockGet).toHaveBeenNthCalledWith(
      1,
      '/tasks/slot-capacity',
      { params: { scheduled_at: '2026-07-05T10:00:00.000Z' } }
    )
    expect(mockGet).toHaveBeenNthCalledWith(2, '/tasks/12/archive')
  })

  it('accepts freeform across task, create, update and preview contracts', async () => {
    const mode: TaskMode = 'freeform'
    const task: Task = createMockTask({ task_mode: mode })
    const createPayload: CreateTaskRequest = {
      issue_id: 7,
      task_mode: mode,
      require_changes: false,
    }
    const updatePayload: UpdateTaskRequest = { task_mode: mode }
    const previewPayload: RunInstructionTemplatePreviewRequest = {
      issue_id: 7,
      task_mode: mode,
      user_prompt: 'Explain the repository',
      require_changes: false,
    }
    mockPost.mockResolvedValue({ data: { id: 12 } })
    mockPatch.mockResolvedValue({ data: { id: 12 } })

    await createTask(createPayload)
    await updateTask(12, updatePayload)
    await previewRunInstructionTemplate(previewPayload)

    expect(task.task_mode).toBe('freeform')
    expect(mockPost).toHaveBeenNthCalledWith(1, '/tasks', createPayload)
    expect(mockPatch).toHaveBeenCalledWith('/tasks/12', updatePayload)
    expect(mockPost).toHaveBeenNthCalledWith(
      2,
      '/tasks/render-run-instruction-template-preview',
      previewPayload,
    )
  })

  it('returns the read-only freeform run-instruction default', async () => {
    const defaults: RunInstructionTemplateDefaults = {
      execute: { content: 'Execute {{user_prompt}}', available_placeholders: ['user_prompt'] },
      freeform: { content: '{{user_prompt}}', available_placeholders: ['user_prompt'] },
      plan: { content: 'Plan {{user_prompt}}', available_placeholders: ['user_prompt'] },
    }
    mockGet.mockResolvedValue({ data: defaults })

    const result = await getRunInstructionTemplateDefaults()

    expect(result.freeform).toEqual({
      content: '{{user_prompt}}',
      available_placeholders: ['user_prompt'],
    })
  })

  it('sends a valid UUID command id', async () => {
    mockPut.mockResolvedValue({ data: { command: { status: 'queued' }, created: true } })

    await sendHarnessCommand(12, { type: 'steer', text: 'continue' })

    expect(mockPut).toHaveBeenCalledOnce()
    const [url, payload] = mockPut.mock.calls[0]
    expect(url).toMatch(
      /^\/tasks\/12\/commands\/[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/,
    )
    expect(payload).toEqual({ type: 'steer', text: 'continue' })
  })

  it('preserves batch, update and done SSE event semantics', () => {
    const onLog = vi.fn()
    const onDone = vi.fn()
    const onUpdate = vi.fn()
    const first: TaskLog = {
      id: 1,
      task_id: 12,
      log_level: 'INFO',
      log_type: 'assistant_text',
      message: 'first',
      created_at: '2026-07-04T10:00:00Z',
    }
    const updated = {
      ...first,
      metadata: { output_payload_id: 99 },
    }

    const source = streamTaskLogs(12, 0, onLog, onDone, onUpdate)
    const fake = FakeEventSource.latest!

    expect(fake.url).toBe('/api/tasks/12/log-stream?since_id=0')

    fake.emit('batch', JSON.stringify([first]))
    fake.emit('update', JSON.stringify(updated))
    fake.emit('done')

    expect(onLog).toHaveBeenCalledWith(first)
    expect(onUpdate).toHaveBeenCalledWith(updated)
    expect(onDone).toHaveBeenCalledOnce()
    expect(source).toBe(fake)
    expect(fake.closed).toBe(true)
  })
})
