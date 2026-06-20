import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
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
  createI18n: () => ({ global: { locale: { value: 'zh-CN' } } }),
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
  const NTabPaneMock = {
    name: 'NTabPane',
    inheritAttrs: false,
    setup(_props: unknown, { attrs, slots }: { attrs: Record<string, unknown>; slots: Record<string, () => unknown> }) {
      return () => h('div', { class: 'NTabPane', ...attrs }, [
        h('div', { class: 'n-tab-pane__tab' }, slots.tab?.() ?? String(attrs.tab ?? '')),
        slots.default?.(),
      ])
    },
  }
  const NBadgeMock = {
    name: 'NBadge',
    inheritAttrs: false,
    props: {
      value: {
        type: [Number, String],
        default: '',
      },
    },
    setup(props: { value: number | string }, { attrs }: { attrs: Record<string, unknown> }) {
      return () => h('sup', { ...attrs, class: ['NBadge', attrs.class] }, String(props.value))
    },
  }
  const NTabMock = {
    name: 'NTab',
    inheritAttrs: false,
    props: {
      name: {
        type: [Number, String],
        required: true,
      },
      tab: {
        type: [Number, String],
        default: '',
      },
      disabled: {
        type: Boolean,
        default: false,
      },
    },
    setup(props: { name: number | string; tab: number | string; disabled: boolean }, { slots, attrs }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown> }) {
      return () => h('button', { ...attrs, class: 'n-tab-pane__tab', disabled: props.disabled }, slots.default?.() ?? String(props.tab || props.name))
    },
  }
  return {
    NCard: NCardMock,
    NTag: makePassthrough('NTag', 'span'),
    NIcon: makePassthrough('NIcon', 'i'),
    NTabs: makePassthrough('NTabs'),
    NTabPane: NTabPaneMock,
    NTab: NTabMock,
    NBadge: NBadgeMock,
    NEmpty: makePassthrough('NEmpty'),
    NCollapse: makePassthrough('NCollapse'),
    NCollapseItem: makePassthrough('NCollapseItem'),
    NButton: makePassthrough('NButton', 'button'),
    NSpin: makePassthrough('NSpin'),
    NScrollbar: {
      name: 'NScrollbar',
      inheritAttrs: false,
      props: ['trigger'],
      setup(props: { trigger?: string }, { slots, attrs, expose }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown>; expose: (obj: Record<string, unknown>) => void }) {
        expose({ scrollTo: vi.fn(), scrollBy: vi.fn() })
        return () => h('div', { ...attrs, class: ['NScrollbar', attrs.class], 'data-trigger': props.trigger }, slots.default?.())
      },
    },
    dateEnUS: {},
    dateZhCN: {},
    enUS: {},
    zhCN: {},
    useMessage: () => ({ error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }),
    useDialog: () => ({}),
  }
})

function flushPromises() {
  return new Promise((resolve) => setTimeout(resolve, 0))
}

async function flushAnimationFrame() {
  await new Promise((resolve) => {
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(() => resolve(undefined))
    else setTimeout(resolve, 0)
  })
  await nextTick()
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

  it('uses segmented tabs for process log switching', () => {
    const wrapper = mountComponent('completed')

    expect(wrapper.getComponent({ name: 'NTabs' }).attributes('type')).toBe('segment')
  })

  it('places the process log tab switcher in the card header', () => {
    const wrapper = mountComponent('completed')

    expect(wrapper.get('.n-card__header .process-tabs').exists()).toBe(true)
    expect(wrapper.find('.n-card__content .process-tabs').exists()).toBe(false)
  })

  it('keeps the header tab switcher compact enough to stay beside the title', () => {
    expect(taskProcessPanelSource).toContain('flex-wrap: nowrap;')
    expect(taskProcessPanelSource).toContain('width: 264px;')
    expect(taskProcessPanelSource).toContain('flex: 0 0 264px;')
  })

  it('keeps event and raw tab content at the same height', () => {
    expect(taskProcessPanelSource).toContain('class="process-content"')
    expect(taskProcessPanelSource).toContain('height: clamp(320px, 52vh, 520px);')
    expect(taskProcessPanelSource).toContain(':deep(.process-content .log-content)')
  })

  it('shows the number of displayed events in the event stream tab', () => {
    const task = createTask('completed')
    const taskLogs: TaskLog[] = [
      {
        id: 11,
        task_id: 1,
        log_level: 'info',
        log_type: 'assistant_text',
        metadata: JSON.stringify({ text: 'first event' }),
        message: '',
        created_at: '2026-04-23T10:00:00Z',
      },
      {
        id: 12,
        task_id: 1,
        log_level: 'info',
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Bash', input: { command: 'pwd' }, output: 'done', error: false }),
        message: '',
        created_at: '2026-04-23T10:00:01Z',
      },
    ]

    const wrapper = mount(TaskProcessPanel, {
      props: {
        task,
        taskLogs,
        isActive: false,
        terminalHtml: '',
        taskStatus: 'completed',
      },
    })

    const eventsTab = wrapper.findAll('.n-tab-pane__tab').find((tab) => tab.text().includes('taskView.eventsTab'))

    expect(eventsTab?.text()).toContain('taskView.eventsTab')
    expect(eventsTab?.find('.event-count-badge').exists()).toBe(true)
    expect(eventsTab?.find('.event-count-badge').text()).toBe('2')
  })

  it('keeps the running background glow subtle', () => {
    expect(taskProcessPanelSource).toContain('rgba(74, 222, 128, 0.07)')
  })

  it('keeps the event count badge muted and centered', () => {
    expect(taskProcessPanelSource).not.toContain('class="event-count-badge" type="info"')
    expect(taskProcessPanelSource).toContain('background: rgba(100, 116, 139, 0.14);')
    expect(taskProcessPanelSource).toContain('justify-content: center;')
  })

  it('uses rounder corners for segmented process tabs and the event badge', () => {
    expect(taskProcessPanelSource).toContain(':deep(.process-tabs .n-tabs-rail)')
    expect(taskProcessPanelSource).toContain(':deep(.process-tabs .n-tabs-capsule)')
    expect(taskProcessPanelSource).toContain('border-radius: 999px;')
  })

  it('renders input preview in tool_call header and output preview in body', async () => {
    const task = createTask('completed')
    const toolCallLog: TaskLog = {
      id: 42,
      task_id: 1,
      log_level: 'info',
      log_type: 'tool_call',
      metadata: JSON.stringify({
        name: 'Bash',
        input: {},
        input_payload_id: 14,
        input_preview: 'git status --short',
        output: null,
        error: false,
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

    const outputButton = wrapper.findAll('button.tool-badge').find((button) => button.text().includes('taskView.toolOutput'))
    expect(outputButton).toBeTruthy()
    await outputButton!.trigger('click')

    expect(wrapper.text()).toContain('git status --short')
    expect(wrapper.text()).toContain('first few lines...')
  })

  it('renders preview for payload-backed assistant text entries', () => {
    const task = createTask('completed')
    const assistantLog: TaskLog = {
      id: 52,
      task_id: 1,
      log_level: 'info',
      log_type: 'assistant_text',
      metadata: JSON.stringify({ payload_id: 21, char_count: 19, preview: 'summary from backend', truncated: false }),
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

    expect(wrapper.text()).toContain('summary from backend')
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
      metadata: JSON.stringify({ payload_id: 21, char_count: 19, preview: 'summary from backend', truncated: false }),
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

    await wrapper.get('button.tool-badge').trigger('click')
    await flushPromises()
    await flushAnimationFrame()

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
      metadata: JSON.stringify({ payload_id: 22, char_count: 10, preview: 'summary from backend', truncated: false }),
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

    await wrapper.get('button.tool-badge').trigger('click')
    await flushPromises()
    await flushAnimationFrame()

    expect(wrapper.text()).toContain('taskView.failedToLoadPayload')
  })
})
