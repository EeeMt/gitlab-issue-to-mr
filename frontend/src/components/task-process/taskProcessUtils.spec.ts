import { describe, expect, it, vi } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import type { TaskLog } from '../../api'
import TaskProcessPanel from '../TaskProcessPanel.vue'
import TaskProcessToolRow from './TaskProcessToolRow.vue'
import { formatInput, getInputSummary, normalizeTaskProcessRows, parseTextEntry, summarizeSkillUsage } from './taskProcessUtils'

vi.mock('vue-i18n', () => ({
  createI18n: () => ({ global: { locale: { value: 'zh-CN' } } }),
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
    NTab: makePassthrough('NTab', 'button'),
    NEmpty: makePassthrough('NEmpty'),
    NCollapse: makePassthrough('NCollapse'),
    NCollapseItem,
    NButton: makePassthrough('NButton', 'button'),
    NBadge: makePassthrough('NBadge', 'span'),
    NSpin: makePassthrough('NSpin'),
    dateEnUS: {},
    dateZhCN: {},
    enUS: {},
    zhCN: {},
  }
})

vi.mock('../utils/format', () => ({
  formatDurationMs: (value: number) => `${value}ms`,
  formatDurationSec: (value: number) => `${value}s`,
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
    ChevronForward: icon,
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
  it('ignores legacy tool_calls_json batches in the normalized event stream', () => {
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

    expect(rows).toHaveLength(1)
    expect(rows.map((row) => row.kind)).toEqual(['tool_call'])
    expect(rows[0].toolCall.name).toBe('Bash')
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

  it('prefers input_preview for payload-backed tool calls', () => {
    expect(getInputSummary({
      name: 'Read',
      input: {},
      output: null,
      error: false,
      input_payload_id: 9,
      input_preview: '/tmp/example.txt',
    })).toBe('/tmp/example.txt')
  })

  it('normalizes context_compact log into a NormalizedCompactRow', () => {
    const log = createTaskLog({ id: 42, log_type: 'context_compact', metadata: JSON.stringify({ session_id: 'abc-123' }) })
    const rows = normalizeTaskProcessRows([log])
    expect(rows).toHaveLength(1)
    expect(rows[0].kind).toBe('context_compact')
    expect(rows[0].event).toBe(log)
  })

  it('context_compact rows are interleaved with other rows in timestamp order', () => {
    const logs: TaskLog[] = [
      createTaskLog({ id: 1, log_type: 'assistant_text', created_at: '2026-05-04T10:00:00Z', metadata: JSON.stringify({ payload_id: null, preview: 'before', truncated: false }) }),
      createTaskLog({ id: 2, log_type: 'context_compact', created_at: '2026-05-04T10:00:01Z', metadata: JSON.stringify({ session_id: 'abc' }) }),
      createTaskLog({ id: 3, log_type: 'assistant_text', created_at: '2026-05-04T10:00:02Z', metadata: JSON.stringify({ payload_id: null, preview: 'after', truncated: false }) }),
    ]
    const rows = normalizeTaskProcessRows(logs)
    expect(rows.map(r => r.kind)).toEqual(['assistant_text', 'context_compact', 'assistant_text'])
  })

  it('summarizes skill usage from the same tool events rendered in task process', () => {
    const logs: TaskLog[] = [
      createTaskLog({
        id: 1,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Skill', input: { skill_name: 'playwright-cli' } }),
      }),
      createTaskLog({
        id: 2,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Skill', input: { path: '/workspace/.agents/skills/playwright-cli/SKILL.md' } }),
      }),
      createTaskLog({
        id: 3,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Skill', input: { skills: [{ name: 'openai-docs', count: 3 }, 'imagegen'] }, output: null, error: false }),
      }),
    ]

    expect(summarizeSkillUsage(logs)).toEqual([
      { name: 'openai-docs', count: 3 },
      { name: 'playwright-cli', count: 2 },
      { name: 'imagegen', count: 1 },
    ])
  })

  it('counts Agent subagent_type as skill usage', () => {
    const agentInput = {
      description: 'Explore scheduled task feature',
      prompt: 'Explore the codebase',
      subagent_type: 'Explore',
    }
    const logs: TaskLog[] = [
      createTaskLog({
        id: 1,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Agent', input: agentInput, output: null, error: false }),
      }),
    ]

    expect(summarizeSkillUsage(logs)).toEqual([
      { name: 'Explore', count: 1 },
    ])
  })

  it('does not deduplicate repeated direct Agent calls with the same input', () => {
    const agentInput = {
      description: 'Explore scheduled task feature',
      prompt: 'Explore the codebase',
      subagent_type: 'Explore',
    }
    const logs: TaskLog[] = [
      createTaskLog({
        id: 1,
        log_type: 'tool_call',
        metadata: JSON.stringify({ name: 'Agent', input: agentInput, output: null, error: false }),
      }),
      createTaskLog({
        id: 2,
        log_type: 'tool_call',
        created_at: '2026-05-04T10:00:01Z',
        metadata: JSON.stringify({ name: 'Agent', input: agentInput, output: null, error: false }),
      }),
    ]

    expect(summarizeSkillUsage(logs)).toEqual([
      { name: 'Explore', count: 2 },
    ])
  })

  it('maps thinking lifecycle keys from object metadata onto ParsedTextEntry', () => {
    const entry = parseTextEntry({
      attempt_id: 'task-1-attempt-1',
      reasoning_id: 'pi-thinking-42',
      status: 'completed',
      started_at: '2026-09-04T01:00:00Z',
      ended_at: '2026-09-04T01:00:48Z',
      duration_ms: 48000,
      payload_id: 7,
      preview: 'final summary',
      char_count: 13,
      truncated: false,
    })

    expect(entry.thinkingStatus).toBe('completed')
    expect(entry.startedAt).toBe('2026-09-04T01:00:00Z')
    expect(entry.endedAt).toBe('2026-09-04T01:00:48Z')
    expect(entry.durationMs).toBe(48000)
    expect(entry.payloadId).toBe(7)
    expect(entry.preview).toBe('final summary')
    expect(entry.text).toBe('')
  })

  it('maps in_progress lifecycle keys from JSON-string metadata', () => {
    const entry = parseTextEntry(JSON.stringify({
      attempt_id: 'task-1-attempt-1',
      reasoning_id: 'pi-thinking-42',
      status: 'in_progress',
      started_at: '2026-09-04T01:00:00Z',
      ended_at: null,
      duration_ms: null,
      payload_id: null,
      preview: '',
      char_count: 0,
      truncated: false,
    }))

    expect(entry.thinkingStatus).toBe('in_progress')
    expect(entry.startedAt).toBe('2026-09-04T01:00:00Z')
    expect(entry.endedAt).toBeNull()
    expect(entry.durationMs).toBeNull()
    expect(entry.payloadId).toBeNull()
  })

  it('maps interrupted status and never coerces invalid duration values', () => {
    const entry = parseTextEntry(JSON.stringify({
      status: 'interrupted',
      started_at: '2026-09-04T01:00:00Z',
      ended_at: '2026-09-04T02:00:00Z',
      duration_ms: 'not-a-number',
    }))

    expect(entry.thinkingStatus).toBe('interrupted')
    expect(entry.startedAt).toBe('2026-09-04T01:00:00Z')
    expect(entry.endedAt).toBe('2026-09-04T02:00:00Z')
    expect(entry.durationMs).toBeNull()

    // Unknown status strings fall back to null rather than an invalid value.
    expect(parseTextEntry(JSON.stringify({ status: 'paused' })).thinkingStatus).toBeNull()
  })

  it('keeps lifecycle fields null when metadata has no lifecycle keys', () => {
    const entry = parseTextEntry(JSON.stringify({
      text: 'static body',
      preview: 'static preview',
      payload_id: 3,
      char_count: 5,
      truncated: false,
    }))

    expect(entry.thinkingStatus).toBeNull()
    expect(entry.startedAt).toBeNull()
    expect(entry.endedAt).toBeNull()
    expect(entry.durationMs).toBeNull()
    // Existing content fields are untouched for legacy static rows.
    expect(entry.text).toBe('static body')
    expect(entry.payloadId).toBe(3)
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
    expect(wrapper.text()).not.toContain('taskView.noToolOutputCaptured')
  })

  it('shows input preview in the header and spinner badge (no body content) for payload-backed tool calls while loading', async () => {
    const wrapper = mount(TaskProcessToolRow, {
      props: {
        row: {
          kind: 'tool_call',
          event: createTaskLog({ metadata: JSON.stringify({ name: 'Read', input: {}, output: null, error: false, input_payload_id: 12, input_preview: '/tmp/example.txt' }) }),
          toolCall: { name: 'Read', input: {}, output: null, error: false, input_payload_id: 12, input_preview: '/tmp/example.txt' },
        },
        inputLoaded: false,
        outputLoaded: false,
        inputLoading: false,
        outputLoading: false,
      },
    })

    await wrapper.get('button.tool-badge').trigger('click')

    // Preview still shows in the event header
    expect(wrapper.text()).toContain('/tmp/example.txt')
    // While payload hasn't loaded, content body is hidden (no placeholder text shown)
    expect(wrapper.text()).not.toContain('taskView.archivedInputPending')
    // Badge shows a spinner (busy state) instead of placeholder text in the body
    expect(wrapper.find('.badge-spin-ring').exists()).toBe(true)
  })

  it('shows failure text for tool payload load errors', async () => {
    const wrapper = mount(TaskProcessToolRow, {
      props: {
        row: {
          kind: 'tool_call',
          event: createTaskLog({ metadata: JSON.stringify({ name: 'Bash', input: {}, output: null, error: false, output_payload_id: 18 }) }),
          toolCall: { name: 'Bash', input: {}, output: null, error: false, output_payload_id: 18 },
        },
        inputLoaded: false,
        outputLoaded: false,
        inputLoading: false,
        outputLoading: false,
        outputFailed: true,
      },
    })

    await wrapper.get('button.tool-badge').trigger('click')

    expect(wrapper.text()).toContain('taskView.failedToLoadPayload')
  })
})

describe('TaskProcessPanel raw pane wiring', () => {
  it('renders the raw pane with terminal html', async () => {
    const wrapper = mount(TaskProcessPanel, {
      props: {
        task: {
          id: 1,
          issue_id: 1,
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

    // Switch to the raw tab to see the terminal html
    ;(wrapper.vm as any).activeTab = 'raw'
    await nextTick()

    expect(wrapper.html()).toContain('hello')
    expect(wrapper.find('pre.log-content').exists()).toBe(true)
  })

  it('renders container summary in runtime info instead of the event stream', () => {
    const wrapper = mount(TaskProcessPanel, {
      props: {
        task: {
          id: 1,
          issue_id: 1,
          project_id: 1,
          user_prompt: 'Prompt',
          status: 'completed',
          priority: 0,
          is_retry: false,
          retry_source_task_id: null,
          scheduled_at: null,
          container_id: 'container-abcdef123456',
          container_name: 'worker-292',
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
        terminalHtml: '',
        taskStatus: 'completed',
      },
    })

    expect(wrapper.text()).toContain('worker-292')
    expect(wrapper.find('.system-init-banner').text()).toContain('worker-292')
    expect(wrapper.find('.empty-state').attributes('description')).toBe('taskView.noLogsAvailable')
    expect(wrapper.find('.event-stream .event-item--container').exists()).toBe(false)
  })
})
