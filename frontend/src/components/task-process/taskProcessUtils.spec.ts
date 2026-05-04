import { describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import type { TaskLog } from '../../api'
import TaskProcessPanel from '../TaskProcessPanel.vue'
import TaskProcessToolRow from './TaskProcessToolRow.vue'
import { formatInput, normalizeTaskProcessRows } from './taskProcessUtils'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('naive-ui', () => {
  const makePassthrough = (name: string, tag = 'div') => ({
    name,
    inheritAttrs: false,
    setup(_props: unknown, { slots, attrs }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown> }) {
      return () => h(tag, { class: name, ...attrs }, slots.default?.())
    },
  })

  const NCollapseItem = {
    name: 'NCollapseItem',
    inheritAttrs: false,
    setup(_props: unknown, { slots, attrs }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown> }) {
      return () => h('div', { class: 'NCollapseItem', ...attrs }, [
        h('div', { class: 'NCollapseItem__header' }, slots.header?.()),
        h('div', { class: 'NCollapseItem__content' }, slots.default?.()),
      ])
    },
  }

  return {
    NCard: {
      name: 'NCard',
      inheritAttrs: false,
      setup(_props: unknown, { attrs, slots }: { attrs: Record<string, unknown>; slots: Record<string, () => unknown> }) {
        return () => h('section', { class: attrs.class, style: attrs.style }, [
          h('header', { class: 'n-card__header' }, slots.header?.()),
          h('div', { class: 'n-card__content' }, slots.default?.()),
        ])
      },
    },
    NTag: makePassthrough('NTag', 'span'),
    NIcon: makePassthrough('NIcon', 'i'),
    NTabs: makePassthrough('NTabs'),
    NTabPane: makePassthrough('NTabPane'),
    NEmpty: makePassthrough('NEmpty'),
    NCollapse: makePassthrough('NCollapse'),
    NCollapseItem,
    NButton: makePassthrough('NButton', 'button'),
    NSpin: makePassthrough('NSpin'),
  }
})

vi.mock('../utils/format', () => ({
  formatDurationMs: (value: number) => `${value}ms`,
}))

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api')
  return {
    ...actual,
    getTaskPayload: vi.fn(),
  }
})

vi.mock('@vicons/ionicons5', () => {
  const icon = { name: 'MockIcon', render: () => h('span') }
  return {
    CubeOutline: icon,
    ArrowDownCircleOutline: icon,
    BulbOutline: icon,
    ChatboxOutline: icon,
    TerminalOutline: icon,
    CreateOutline: icon,
    DocumentTextOutline: icon,
    PencilOutline: icon,
    SearchOutline: icon,
    ExtensionPuzzleOutline: icon,
    ServerOutline: icon,
  }
})

function createTaskLog(overrides: Partial<TaskLog>): TaskLog {
  return {
    id: 1,
    task_id: 1,
    log_level: 'info',
    log_type: 'tool_call',
    metadata: null,
    message: '',
    created_at: '2026-05-04T10:00:00Z',
    ...overrides,
  }
}

describe('taskProcessUtils', () => {
  it('keeps both individual and batched tool calls when both formats are present', () => {
    const logs: TaskLog[] = [
      createTaskLog({
        id: 10,
        log_type: 'tool_calls_json',
        metadata: JSON.stringify([
          { name: 'Read', input: { file_path: '/tmp/a' }, output: null, error: false },
        ]),
      }),
      createTaskLog({
        id: 11,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Bash', input: { command: 'pwd' }, output: '', error: false }),
      }),
    ]

    const rows = normalizeTaskProcessRows(logs)

    expect(rows).toHaveLength(2)
    expect(rows.map((row) => row.kind)).toEqual(['tool_call', 'tool_call'])
    expect(rows.map((row) => row.toolCall.name).sort()).toEqual(['Bash', 'Read'])
  })

  it('formats Edit input using old_string and new_string keys', () => {
    const formatted = formatInput({
      name: 'Edit',
      input: {
        file_path: '/tmp/demo.txt',
        old_string: 'before',
        new_string: 'after',
      },
      output: null,
      error: false,
    })

    expect(formatted).toContain('file: /tmp/demo.txt')
    expect(formatted).toContain('--- (old)\nbefore')
    expect(formatted).toContain('+++ (new)\nafter')
  })
})

describe('TaskProcessToolRow', () => {
  it('shows the output section when tool output is an empty string', () => {
    const wrapper = mount(TaskProcessToolRow, {
      props: {
        row: {
          kind: 'tool_call',
          event: createTaskLog({ metadata: JSON.stringify({ name: 'Bash', input: { command: 'true' }, output: '', error: false }) }),
          toolCall: { name: 'Bash', input: { command: 'true' }, output: '', error: false },
        },
        inputLoaded: false,
        outputLoaded: false,
        inputLoading: false,
        outputLoading: false,
      },
    })

    expect(wrapper.text()).toContain('taskView.toolOutput')
  })
})

describe('TaskProcessPanel raw pane wiring', () => {
  it('renders the raw pane with terminal html', async () => {
    const wrapper = mount(TaskProcessPanel, {
      props: {
        task: {
          id: 1,
          issue_id: null,
          project_id: 1,
          user_prompt: 'Prompt',
          status: 'completed',
          priority: 0,
          is_retry: false,
          retry_source_task_id: null,
          scheduled_at: null,
          container_id: 'container-1',
          container_name: 'container-1',
          commit_sha: null,
          error_message: null,
          additions: 0,
          deletions: 0,
          total_changes: 0,
          input_tokens: null,
          output_tokens: null,
          provider_id: null,
          created_at: '2026-05-04T10:00:00Z',
          updated_at: '2026-05-04T10:00:00Z',
          started_at: null,
          completed_at: null,
        },
        taskLogs: [],
        isActive: false,
        terminalHtml: '<span>hello</span>',
        taskStatus: 'completed',
      },
    })

    await nextTick()

    expect(wrapper.html()).toContain('hello')
    expect(wrapper.find('pre.log-content').exists()).toBe(true)
  })
})
