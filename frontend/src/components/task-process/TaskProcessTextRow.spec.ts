import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { h, nextTick } from 'vue'
import { mount } from '@vue/test-utils'
import type { TaskLog } from '../../api'

const { renderMarkdownMock } = vi.hoisted(() => ({
  renderMarkdownMock: vi.fn((text: string) => `<p>${text}</p>`),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
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

  it('shows badge as loading while the payload API fetch is in progress', async () => {
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
        expandedText: '',
        loading: true,
        showContent: false,
      },
    })

    await wrapper.get('button.tool-badge').trigger('click')

    // No text yet — nothing rendered, badge shows loading spinner.
    expect(renderMarkdownMock).not.toHaveBeenCalled()
    expect(wrapper.get('button.tool-badge').classes()).toContain('tool-badge--loading')

    // Payload arrives.
    await wrapper.setProps({ expandedText: '**full assistant body**', showContent: true, loading: false })
    await nextTick()

    expect(renderMarkdownMock).toHaveBeenCalledWith('**full assistant body**')
    expect(wrapper.get('button.tool-badge').classes()).not.toContain('tool-badge--loading')
    expect(wrapper.html()).toContain('<p>**full assistant body**</p>')
  })
})
