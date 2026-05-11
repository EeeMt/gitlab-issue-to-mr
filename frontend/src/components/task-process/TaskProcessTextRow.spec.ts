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
  const rafCallbacks: FrameRequestCallback[] = []

  beforeEach(() => {
    renderMarkdownMock.mockClear()
    rafCallbacks.length = 0
    vi.stubGlobal('requestAnimationFrame', vi.fn((callback: FrameRequestCallback) => {
      rafCallbacks.push(callback)
      return rafCallbacks.length
    }))
    vi.stubGlobal('cancelAnimationFrame', vi.fn())
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  async function flushAnimationFrame() {
    const callbacks = rafCallbacks.splice(0)
    callbacks.forEach((callback) => callback(0))
    await nextTick()
  }

  it('keeps the badge loading while full text markdown is prepared off the click render path', async () => {
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

    await wrapper.get('button.tool-badge').trigger('click')

    expect(renderMarkdownMock).not.toHaveBeenCalled()
    expect(wrapper.get('button.tool-badge').classes()).toContain('tool-badge--loading')

    await flushAnimationFrame()

    expect(renderMarkdownMock).toHaveBeenCalledWith('**full assistant body**')
    expect(wrapper.get('button.tool-badge').classes()).not.toContain('tool-badge--loading')
    expect(wrapper.html()).toContain('<p>**full assistant body**</p>')
  })
})
