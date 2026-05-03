import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import type { Task, TaskLog } from '../api'
import TaskProcessPanel from './TaskProcessPanel.vue'
import taskProcessPanelSource from './TaskProcessPanel.vue?raw'

// Use vi.hoisted so the mock factory runs before vi.mock hoisting
const { mockGetTaskPayload } = vi.hoisted(() => {
  return { mockGetTaskPayload: vi.fn() }
})

vi.mock('../api', () => ({
  getTaskPayload: mockGetTaskPayload,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

// Mock naive-ui so all components render their slots without styling overhead
vi.mock('naive-ui', () => {
  const makePassthrough = (name: string, tag = 'div') => ({
    name,
    inheritAttrs: false,
    setup(_props: unknown, { slots, attrs }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown> }) {
      return () => h(tag, { class: name, ...attrs }, slots.default?.())
    },
  })
  const NCardMock = {
    name: 'NCard',
    inheritAttrs: false,
    setup(_props: unknown, { attrs, slots }: { attrs: Record<string, unknown>; slots: Record<string, () => unknown> }) {
      return () => h('section', { class: attrs.class, style: attrs.style }, [
        h('header', { class: 'n-card__header' }, slots.header?.()),
        h('div', { class: 'n-card__content' }, slots.default?.()),
      ])
    },
  }
  return {
    NCard: NCardMock,
    NTag: makePassthrough('NTag', 'span'),
    NIcon: makePassthrough('NIcon', 'i'),
    NTabs: makePassthrough('NTabs'),
    NTabPane: makePassthrough('NTabPane'),
    NEmpty: makePassthrough('NEmpty'),
    NCollapse: makePassthrough('NCollapse'),
    NCollapseItem: makePassthrough('NCollapseItem'),
    NButton: makePassthrough('NButton', 'button'),
    NSpin: makePassthrough('NSpin'),
    useMessage: () => ({ error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }),
    useDialog: () => ({}),
  }
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

function createTask(status: Task['status']): Task {
  return {
    id: 1,
    issue_id: null,
    project_id: 1,
    user_prompt: 'Prompt',
    status,
    priority: 0,
    is_retry: false,
    retry_source_task_id: null,
    scheduled_at: null,
    container_id: null,
    container_name: null,
    commit_sha: null,
    error_message: null,
    additions: 0,
    deletions: 0,
    total_changes: 0,
    input_tokens: null,
    output_tokens: null,
    provider_id: null,
    created_at: '2026-04-23T10:00:00Z',
    updated_at: '2026-04-23T10:00:00Z',
    started_at: null,
    completed_at: null,
  }
}

function mountComponent(status: Task['status']) {
  return mount(TaskProcessPanel, {
    props: {
      task: createTask(status),
      taskLogs: [],
      isActive: status === 'running' || status === 'queued' || status === 'pending',
      terminalHtml: '',
      taskStatus: status,
    },
  })
}

describe('TaskProcessPanel', () => {
  beforeEach(() => {
    mockGetTaskPayload.mockReset()
  })

  it('adds the running glow class to the card when the task is running', () => {
    const wrapper = mountComponent('running')

    expect(wrapper.get('.task-process-panel').classes()).toContain('task-process-panel--running')
  })

  it('keeps the running background glow subtle', () => {
    expect(taskProcessPanelSource).toContain('rgba(74, 222, 128, 0.07)')
  })

  it('renders output preview for tool_call entries with output_payload_id', () => {
    const task = createTask('completed')
    const toolCallLog: TaskLog = {
      id: 42,
      task_id: 1,
      log_level: 'info',
      log_type: 'tool_call',
      metadata: JSON.stringify({
        name: 'Bash',
        input: { command: 'cat large_file.txt' },
        output: null,
        error: false,
        output_payload_id: 15,
        output_preview: 'first few lines...',
        output_truncated: true,
      }),
      message: '',
      created_at: '2026-04-23T10:00:00Z',
    }

    const wrapper = mount(TaskProcessPanel, {
      props: {
        task,
        taskLogs: [toolCallLog],
        isActive: false,
        terminalHtml: '',
        taskStatus: 'completed',
      },
    })

    expect(wrapper.text()).toContain('first few lines...')
  })

  it('loads payload-backed assistant text on expand and clears loading state', async () => {
    mockGetTaskPayload.mockResolvedValue({
      id: 21,
      payload_kind: 'assistant_text',
      content: 'full assistant body',
      encoding: 'identity',
      char_count: 19,
      byte_count: 19,
    })
    const task = createTask('completed')
    const assistantLog: TaskLog = {
      id: 43,
      task_id: 1,
      log_level: 'info',
      log_type: 'assistant_text',
      metadata: JSON.stringify({ payload_id: 21, char_count: 19 }),
      message: '',
      created_at: '2026-04-23T10:00:00Z',
    }

    const wrapper = mount(TaskProcessPanel, {
      props: {
        task,
        taskLogs: [assistantLog],
        isActive: false,
        terminalHtml: '',
        taskStatus: 'completed',
      },
    })

    await (wrapper.vm as unknown as { onCollapseChange: (names: string[], index: number) => void }).onCollapseChange(['detail'], 0)
    await flushPromises()

    expect(mockGetTaskPayload).toHaveBeenCalledWith(1, 21)
    expect(wrapper.text()).toContain('full assistant body')
    expect(wrapper.text()).not.toContain('failedToLoadPayload')
  })

  it('shows failure text when assistant payload loading fails', async () => {
    mockGetTaskPayload.mockRejectedValue(new Error('boom'))
    const task = createTask('completed')
    const assistantLog: TaskLog = {
      id: 44,
      task_id: 1,
      log_level: 'info',
      log_type: 'assistant_text',
      metadata: JSON.stringify({ payload_id: 22, char_count: 10 }),
      message: '',
      created_at: '2026-04-23T10:00:00Z',
    }

    const wrapper = mount(TaskProcessPanel, {
      props: {
        task,
        taskLogs: [assistantLog],
        isActive: false,
        terminalHtml: '',
        taskStatus: 'completed',
      },
    })

    await (wrapper.vm as unknown as { onCollapseChange: (names: string[], index: number) => void }).onCollapseChange(['detail'], 0)
    await flushPromises()

    expect(wrapper.text()).toContain('taskView.failedToLoadPayload')
  })
})
