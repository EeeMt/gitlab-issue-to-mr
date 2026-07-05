import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import TaskResultPanel from './TaskResultPanel.vue'
import { createMockTask, createMockTaskLog } from '../test/mocks/api'

const { iconStub, mockGetTaskPayload, mockMessage, mockMermaidRender } = vi.hoisted(() => ({
  iconStub: {
    setup() {
      return () => h('svg', { class: 'icon-stub' })
    },
  },
  mockGetTaskPayload: vi.fn(),
  mockMessage: {
    success: vi.fn(),
    error: vi.fn(),
  },
  mockMermaidRender: vi.fn(),
}))

const messages: Record<string, string> = {
  'taskView.copySource': 'Copy source',
  'taskView.copied': 'Copied',
  'taskView.copyFailed': 'Copy failed',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => messages[key] ?? key,
  }),
}))

vi.mock('../api', () => ({
  getTaskPayload: mockGetTaskPayload,
}))

vi.mock('mermaid', () => ({
  default: {
    initialize: vi.fn(),
    render: mockMermaidRender,
  },
}))

vi.mock('@vicons/ionicons5', () => ({
  AlertCircleOutline: iconStub,
  GitCommitOutline: iconStub,
  OpenOutline: iconStub,
  ChevronForward: iconStub,
  ChatboxOutline: iconStub,
  Checkmark: iconStub,
  CopyOutline: iconStub,
  ExpandOutline: iconStub,
}))

vi.mock('naive-ui', () => ({
  NCard: {
    setup(_props: unknown, { slots }: any) {
      return () => h('section', [slots.header?.(), slots.default?.()])
    },
  },
  NIcon: {
    setup(_props: unknown, { slots }: any) {
      return () => h('span', { class: 'n-icon' }, slots.default?.())
    },
  },
  NButton: {
    props: ['disabled'],
    setup(props: any, { attrs, slots }: any) {
      return () => h('button', { ...attrs, disabled: props.disabled }, [
        slots.icon?.(),
        slots.default?.(),
      ])
    },
  },
  NInputNumber: {
    setup(_props: unknown, { attrs }: any) {
      return () => h('input', attrs)
    },
  },
  NModal: {
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('section', [slots.header?.(), slots.default?.()]) : null
    },
  },
  NScrollbar: {
    setup(_props: unknown, { slots }: any) {
      return () => h('div', slots.default?.())
    },
  },
  NTooltip: {
    setup(_props: unknown, { slots }: any) {
      return () => h('div', slots.trigger?.())
    },
  },
  useMessage: () => mockMessage,
}))

function mountPanel(metadata: Record<string, unknown>) {
  return mount(TaskResultPanel, {
    props: {
      task: createMockTask({ id: 12, status: 'completed' }),
      deliverySummaryLog: createMockTaskLog({
        id: 34,
        task_id: 12,
        metadata,
      }),
    },
  })
}

describe('TaskResultPanel copy interactions', () => {
  const clipboardWrite = vi.fn()

  beforeEach(() => {
    clipboardWrite.mockReset()
    clipboardWrite.mockResolvedValue(undefined)
    mockGetTaskPayload.mockReset()
    mockMessage.success.mockReset()
    mockMessage.error.mockReset()
    mockMermaidRender.mockReset()
    mockMermaidRender.mockResolvedValue({ svg: '<svg></svg>' })
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true,
      value: { writeText: clipboardWrite },
    })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('keeps summary actions as sibling buttons instead of nesting interactive controls', () => {
    const wrapper = mountPanel({ text: 'Summary source' })
    const trigger = wrapper.get('.summary-trigger')

    expect(trigger.element.tagName).toBe('DIV')
    expect(trigger.findAll('button button')).toHaveLength(0)
    expect(trigger.findAll('button [role="button"]')).toHaveLength(0)
  })

  it('loads and copies the complete payload-backed summary source', async () => {
    mockGetTaskPayload.mockResolvedValue({ content: 'Complete **raw** summary' })
    const wrapper = mountPanel({
      text: '',
      preview: 'Complete raw…',
      payload_id: 91,
      truncated: true,
    })

    await wrapper.get('[aria-label="Copy source"]').trigger('click')
    await flushPromises()

    expect(mockGetTaskPayload).toHaveBeenCalledWith(12, 91)
    expect(clipboardWrite).toHaveBeenCalledWith('Complete **raw** summary')
  })

  it('does not copy stale payload content after the selected summary changes', async () => {
    let resolveFirstPayload!: (value: { content: string }) => void
    let resolveSecondPayload!: (value: { content: string }) => void
    mockGetTaskPayload
      .mockImplementationOnce(() => new Promise(resolve => {
        resolveFirstPayload = resolve
      }))
      .mockImplementationOnce(() => new Promise(resolve => {
        resolveSecondPayload = resolve
      }))

    const wrapper = mountPanel({
      text: '',
      preview: 'Old summary',
      payload_id: 91,
      truncated: true,
    })
    void wrapper.get('[aria-label="Copy source"]').trigger('click')
    await nextTick()

    await wrapper.setProps({
      deliverySummaryLog: createMockTaskLog({
        id: 35,
        task_id: 12,
        metadata: {
          text: '',
          preview: 'New summary',
          payload_id: 92,
          truncated: true,
        },
      }),
    })
    void wrapper.get('[aria-label="Copy source"]').trigger('click')
    await nextTick()

    resolveSecondPayload({ content: 'New complete summary' })
    await flushPromises()
    resolveFirstPayload({ content: 'Old complete summary' })
    await flushPromises()

    expect(clipboardWrite).toHaveBeenCalledTimes(1)
    expect(clipboardWrite).toHaveBeenCalledWith('New complete summary')
  })

  it('restores the Mermaid copy label after repeated successful copies', async () => {
    vi.useFakeTimers()
    const wrapper = mountPanel({
      text: '```mermaid\ngraph TD\nA --> B\n```',
    })

    const summaryToggle = wrapper.find('button.summary-trigger__main').exists()
      ? wrapper.get('button.summary-trigger__main')
      : wrapper.get('button.summary-trigger')
    await summaryToggle.trigger('click')
    await flushPromises()
    await nextTick()

    const copyButton = wrapper.get<HTMLButtonElement>('.summary-mermaid__copy')
    await copyButton.trigger('click')
    await flushPromises()
    expect(copyButton.text()).toBe('Copied')

    vi.advanceTimersByTime(500)
    await copyButton.trigger('click')
    await flushPromises()
    vi.advanceTimersByTime(2000)
    await nextTick()

    expect(copyButton.text()).toBe('Copy source')
    expect(clipboardWrite).toHaveBeenCalledTimes(2)
    expect(clipboardWrite).toHaveBeenLastCalledWith('graph TD\nA --> B')
  })
})
