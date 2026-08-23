import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: vi.fn((key: string) => key) }),
}))

vi.mock('naive-ui', async (importOriginal) => {
  const actual = await importOriginal<typeof import('naive-ui')>()
  return {
    ...actual,
    useMessage: () => ({ success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() }),
  }
})
vi.mock('../api/tasks', () => ({
  listHarnessCommands: vi.fn().mockResolvedValue([]),
  sendHarnessCommand: vi.fn(),
}))
import { flushPromises, mount } from '@vue/test-utils'
import { listHarnessCommands } from '../api/tasks'
import TaskSteeringPanel from './TaskSteeringPanel.vue'

// The i18n mock resolves keys as-is; naive-ui components stub out.
const globalStubs = {
  'n-radio-group': true,
  'n-radio-button': true,
  'n-input': true,
  'n-button': true,
}

function mountPanel(props: Record<string, unknown>) {
  return mount(TaskSteeringPanel, {
    props: {
      taskId: 1,
      taskStatus: 'running',
      controlState: 'accepting',
      capabilities: { steering: true, follow_up: true },
      ...props,
    },
    global: { stubs: globalStubs },
  })
}

describe('TaskSteeringPanel', () => {
  beforeEach(() => {
    vi.mocked(listHarnessCommands).mockReset()
    vi.mocked(listHarnessCommands).mockResolvedValue([])
  })
  it('renders for a running accepting catalog-capable attempt', () => {
    const w = mountPanel({})
    expect(w.find('[data-testid="steering-panel"]').exists()).toBe(true)
    expect(w.find('[data-testid="steering-gate-accepting"]').exists()).toBe(true)
  })

  it('is hidden when the frozen catalog declares no control capability', () => {
    const w = mountPanel({ capabilities: { steering: false, follow_up: false } })
    expect(w.find('[data-testid="steering-panel"]').exists()).toBe(false)
  })

  it('shows transition hint when gate is starting', () => {
    const w = mountPanel({ controlState: 'starting' })
    expect(w.find('[data-testid="steering-gate-starting"]').exists()).toBe(true)
    expect(w.find('[data-testid="steering-hint"]').exists()).toBe(true)
  })

  it('disables input unless the gate is accepting and task is running', () => {
    const done = mountPanel({ taskStatus: 'completed' })
    expect(done.find('[data-testid="steering-gate-accepting"]').exists()).toBe(true)
  })

  it('does not use a harness key to determine visibility', () => {
    const w = mountPanel({ capabilities: { steering: true }, harnessKey: 'not-a-real-harness' })
    expect(w.find('[data-testid="steering-panel"]').exists()).toBe(true)
  })

  it('renders the complete command lifecycle without rendering command text', async () => {
    vi.mocked(listHarnessCommands).mockResolvedValueOnce([
      {
        command_id: 'queued', sequence_no: 1, type: 'steer',
        status: 'queued', created_at: '2026-08-23T00:00:00Z',
        dispatch_started_at: null, native_ack_at: null, outcome_unknown_at: null,
        delivered_at: null, rejected_at: null, rejection_code: null, rejection_message: null,
      },
      {
        command_id: 'dispatching', sequence_no: 2, type: 'steer',
        status: 'dispatching', created_at: '2026-08-23T00:00:00Z',
        dispatch_started_at: '2026-08-23T00:00:01Z', native_ack_at: null, outcome_unknown_at: null,
        delivered_at: null, rejected_at: null, rejection_code: null, rejection_message: null,
      },
      {
        command_id: 'delivered', sequence_no: 3, type: 'follow_up',
        status: 'delivered', created_at: '2026-08-23T00:00:00Z',
        dispatch_started_at: null, native_ack_at: '2026-08-23T00:00:02Z', outcome_unknown_at: null,
        delivered_at: '2026-08-23T00:00:02Z', rejected_at: null, rejection_code: null, rejection_message: null,
      },
      {
        command_id: 'rejected', sequence_no: 4, type: 'steer',
        status: 'rejected', created_at: '2026-08-23T00:00:00Z',
        dispatch_started_at: null, native_ack_at: null, outcome_unknown_at: null,
        delivered_at: null, rejected_at: '2026-08-23T00:00:03Z', rejection_code: 'closed', rejection_message: 'gate closed',
      },
      {
        command_id: 'unknown', sequence_no: 5, type: 'steer',
        status: 'outcome_unknown', created_at: '2026-08-23T00:00:00Z',
        dispatch_started_at: null, native_ack_at: null, outcome_unknown_at: '2026-08-23T00:00:04Z',
        delivered_at: null, rejected_at: null, rejection_code: 'unknown', rejection_message: 'native acknowledgement lost',
      },
    ])
    const w = mountPanel({})
    await flushPromises()
    for (const status of ['queued', 'dispatching', 'delivered', 'rejected', 'outcome_unknown']) {
      expect(w.find(`[data-testid="steering-command-${status}"]`).exists()).toBe(true)
    }
    expect(w.text()).not.toContain('command secret')
  })

  it('loads history only after a delayed catalog capability makes the panel visible', async () => {
    vi.mocked(listHarnessCommands).mockResolvedValueOnce([
      {
        command_id: 'after-catalog', sequence_no: 1, type: 'steer', status: 'queued',
        created_at: '2026-08-23T00:00:00Z', dispatch_started_at: null, native_ack_at: null,
        outcome_unknown_at: null, delivered_at: null, rejected_at: null,
        rejection_code: null, rejection_message: null,
      },
    ])
    const w = mountPanel({ capabilities: null })
    expect(w.find('[data-testid="steering-panel"]').exists()).toBe(false)
    expect(listHarnessCommands).not.toHaveBeenCalled()

    await w.setProps({ capabilities: { steering: true } })
    await flushPromises()

    expect(listHarnessCommands).toHaveBeenCalledWith(1)
    expect(w.find('[data-testid="steering-history"]').text()).toContain('#1')
  })

  it('clears task-local history before the next task history resolves', async () => {
    let resolveFirst!: (value: any[]) => void
    let resolveSecond!: (value: any[]) => void
    vi.mocked(listHarnessCommands)
      .mockImplementationOnce(() => new Promise(resolve => { resolveFirst = resolve }))
      .mockImplementationOnce(() => new Promise(resolve => { resolveSecond = resolve }))
    const w = mountPanel({})
    await w.setProps({ taskId: 2 })
    expect(w.find('[data-testid="steering-history"]').exists()).toBe(false)

    resolveFirst([{ command_id: 'stale', sequence_no: 1, type: 'steer', status: 'queued', created_at: 'x', dispatch_started_at: null, native_ack_at: null, outcome_unknown_at: null, delivered_at: null, rejected_at: null, rejection_code: null, rejection_message: null }])
    await flushPromises()
    expect(w.text()).not.toContain('stale')

    resolveSecond([{ command_id: 'current', sequence_no: 2, type: 'steer', status: 'queued', created_at: 'x', dispatch_started_at: null, native_ack_at: null, outcome_unknown_at: null, delivered_at: null, rejected_at: null, rejection_code: null, rejection_message: null }])
    await flushPromises()
    expect(w.find('[data-testid="steering-history"]').text()).toContain('#2')
  })
})
