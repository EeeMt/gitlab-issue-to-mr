import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import type { TaskLog } from '../../api'

const { renderMarkdownMock } = vi.hoisted(() => ({
  renderMarkdownMock: vi.fn((text: string) => `<p>${text}</p>`),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    // Plain keys render verbatim; interpolated messages surface as `key:time`
    // so tests can assert the translated-message shape without hardcoding locale.
    t: (key: string, named?: Record<string, unknown>) =>
      named === undefined ? key : `${key}:${String(named.time ?? '')}`,
  }),
}))

vi.mock('naive-ui', () => ({
  NIcon: {
    name: 'NIcon',
    inheritAttrs: false,
    setup(_props: unknown, { slots, attrs }: { slots: Record<string, () => unknown>; attrs: Record<string, unknown> }) {
      return () => h('i', { class: 'NIcon', ...attrs }, slots.default?.())
    },
  },
}))

vi.mock('@vicons/ionicons5', () => {
  const icon = { name: 'MockIcon', render: () => h('span') }
  return {
    BulbOutline: icon,
    ChatboxOutline: icon,
    ChevronForward: icon,
  }
})

vi.mock('./taskProcessUtils', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./taskProcessUtils')>()
  return {
    ...actual,
    renderMarkdown: renderMarkdownMock,
  }
})

import TaskProcessTextRow from './TaskProcessTextRow.vue'

function createTaskLog(): TaskLog {
  return {
    id: 1,
    task_id: 1,
    log_level: 'info',
    log_type: 'assistant_text',
    metadata: null,
    message: '',
    created_at: '2026-05-04T10:00:00Z',
  }
}

describe('TaskProcessTextRow', () => {
  beforeEach(() => {
    renderMarkdownMock.mockClear()
  })

  it('pre-renders markdown eagerly when text and showContent are both available', async () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'assistant_text',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: 'summary',
            payloadId: 21,
            charCount: 22,
            truncated: true,
          },
        },
        expandedText: '**full assistant body**',
        loading: false,
        showContent: true,
      },
    })

    // Rendering happens synchronously on mount — no RAF or click required.
    expect(renderMarkdownMock).toHaveBeenCalledWith('**full assistant body**')

    // Clicking the badge reveals the pre-rendered content immediately.
    await wrapper.get('button.tool-badge').trigger('click')

    expect(wrapper.get('button.tool-badge').classes()).not.toContain('tool-badge--loading')
    expect(wrapper.html()).toContain('<p>**full assistant body**</p>')
  })

  it('shows a ticking in-progress thinking label with a spinner and no full-text controls', async () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'in_progress',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: null,
            durationMs: null,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T01:00:15Z'),
        taskActive: true,
      },
    })

    // Fake wall clock 15s after started_at drives the elapsed suffix.
    expect(wrapper.get('.event-name').text()).toContain('taskView.thinkingInProgress')
    expect(wrapper.get('.event-name').text()).toContain('15s')
    // Live record: spinner, no preview, no full-text button, no content sections.
    expect(wrapper.find('.thinking-spinner').exists()).toBe(true)
    expect(wrapper.find('.event-preview').exists()).toBe(false)
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
    expect(wrapper.find('.tool-sections').exists()).toBe(false)

    // Elapsed comes exclusively from the nowMs prop — ticking never re-parses
    // logs or re-renders markdown.
    await wrapper.setProps({ nowMs: Date.parse('2026-09-04T01:00:38Z') })
    expect(wrapper.get('.event-name').text()).toContain('38s')
    expect(renderMarkdownMock).not.toHaveBeenCalled()
  })

  it('shows a label with no time suffix when in-progress has no usable startedAt', () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'in_progress',
            startedAt: null,
            endedAt: null,
            durationMs: null,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T01:00:38Z'),
        taskActive: true,
      },
    })

    const nameText = wrapper.get('.event-name').text()
    // Never NaN — plain live label plus spinner, no timer suffix.
    expect(nameText).toBe('taskView.thinkingLabel')
    expect(nameText).not.toMatch(/NaN/)
    expect(wrapper.find('.thinking-spinner').exists()).toBe(true)
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
  })

  it('derives an interrupted display when an in_progress thinking record outlives the task', () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'in_progress',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: null,
            durationMs: null,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    expect(wrapper.get('.event-name').text()).toContain('taskView.thinkingInterrupted')
    expect(wrapper.find('.thinking-spinner').exists()).toBe(false)
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
    expect(wrapper.find('.event-preview').exists()).toBe(false)
  })

  it('shows interrupted thinking without preview or full-text controls', () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'interrupted',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: '2026-09-04T01:02:00Z',
            durationMs: null,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    expect(wrapper.get('.event-name').text()).toContain('taskView.thinkingInterrupted')
    expect(wrapper.find('.thinking-spinner').exists()).toBe(false)
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
    expect(wrapper.find('.event-preview').exists()).toBe(false)
  })

  it('shows completed thinking with the server duration even for empty content', () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'completed',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: '2026-09-04T01:00:48Z',
            durationMs: 48000,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    // '思考完成 · 耗时 X'-style label is asserted through the message key plus
    // the interpolated time — not hardcoded zh text.
    const nameText = wrapper.get('.event-name').text()
    expect(nameText).toContain('taskView.thinkingCompletedWithTime')
    expect(nameText).toContain('48s')
    expect(wrapper.find('.thinking-spinner').exists()).toBe(false)
    // Empty completion: no full-text entry point.
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
    expect(wrapper.find('.tool-sections').exists()).toBe(false)
  })

  it('shows completed thinking without a time suffix when duration is unknown', () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: '',
            payloadId: null,
            charCount: 0,
            truncated: false,
            thinkingStatus: 'completed',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: null,
            durationMs: null,
          },
        },
        expandedText: '',
        loading: false,
        showContent: false,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    const nameText = wrapper.get('.event-name').text()
    expect(nameText).toBe('taskView.thinkingCompleted')
    expect(wrapper.find('button.tool-badge').exists()).toBe(false)
  })

  it('keeps the full-text button for completed thinking backed by a payload', async () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: '',
            preview: 'final summary',
            payloadId: 21,
            charCount: 13,
            truncated: false,
            thinkingStatus: 'completed',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: '2026-09-04T01:00:48Z',
            durationMs: 48000,
          },
        },
        expandedText: '**full thinking body**',
        loading: false,
        showContent: true,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    expect(wrapper.find('.event-preview').exists()).toBe(true)
    expect(wrapper.get('.event-preview').text()).toContain('final summary')
    expect(wrapper.get('button.tool-badge').text()).toContain('taskView.fullText')

    // Expansion behaves exactly like today's rows.
    await wrapper.get('button.tool-badge').trigger('click')
    expect(wrapper.emitted('collapse-change')).toEqual([[['detail']]])
    expect(wrapper.html()).toContain('<p>**full thinking body**</p>')
    await wrapper.get('button.tool-badge').trigger('click')
    expect(wrapper.emitted('collapse-change')).toEqual([[['detail']], [[]]])
  })

  it('keeps the full-text button for completed thinking with inline text content', async () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: 'inline thinking body',
            preview: 'inline thinking body',
            payloadId: null,
            charCount: 20,
            truncated: false,
            thinkingStatus: 'completed',
            startedAt: '2026-09-04T01:00:00Z',
            endedAt: '2026-09-04T01:00:10Z',
            durationMs: 10000,
          },
        },
        expandedText: 'inline thinking body',
        loading: false,
        showContent: true,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    expect(wrapper.find('button.tool-badge').exists()).toBe(true)
  })

  it('keeps today static display for thinking rows without lifecycle keys', async () => {
    const wrapper = mount(TaskProcessTextRow, {
      props: {
        row: {
          kind: 'thinking',
          event: createTaskLog(),
          textEntry: {
            text: 'legacy body',
            preview: 'legacy preview',
            payloadId: null,
            charCount: 11,
            truncated: false,
          },
        },
        expandedText: 'legacy body',
        loading: false,
        showContent: true,
        nowMs: Date.parse('2026-09-04T02:00:00Z'),
        taskActive: false,
      },
    })

    expect(wrapper.get('.event-name').text()).toBe('taskView.thinkingLabel')
    expect(wrapper.get('.event-preview').text()).toContain('legacy preview')
    expect(wrapper.find('.thinking-spinner').exists()).toBe(false)
    expect(wrapper.find('button.tool-badge').exists()).toBe(true)

    await wrapper.get('button.tool-badge').trigger('click')
    expect(wrapper.html()).toContain('<p>legacy body</p>')
  })
})
