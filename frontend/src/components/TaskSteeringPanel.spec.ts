import { describe, expect, it, vi } from 'vitest'

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
import { mount } from '@vue/test-utils'
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
      harnessKey: 'pi',
      controlState: 'accepting',
      ...props,
    },
    global: { stubs: globalStubs },
  })
}

describe('TaskSteeringPanel', () => {
  it('renders for a running accepting Pi attempt', () => {
    const w = mountPanel({})
    expect(w.find('[data-testid="steering-panel"]').exists()).toBe(true)
    expect(w.find('[data-testid="steering-gate-accepting"]').exists()).toBe(true)
  })

  it('is hidden for non-command harnesses', () => {
    const w = mountPanel({ harnessKey: 'claude' })
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
})
