import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import TaskResultPanel from './TaskResultPanel.vue'
import { createMockTask, createMockTaskLog } from '../test/mocks/api'
import type { Task, TaskGitDelivery } from '../api'

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
  'taskView.gitDeliveryStatsUnavailable': 'Change stats not collected',
  'taskView.gitDeliveryBranch': 'Branch: {branch}',
  'taskView.gitDeliveryCommits': 'This task commits ({count})',
  'taskView.gitDeliveryRecovered': 'Recovered delivery ({count})',
  'taskView.gitDeliveryPush': 'Push:',
  'taskView.gitDeliveryPushed': 'Pushed',
  'taskView.gitDeliveryAlreadyPresent': 'Already on remote',
  'taskView.gitDeliveryNotNeeded': 'Nothing to deliver',
  'taskView.gitDeliveryNotAttempted': 'Push not attempted',
  'taskView.gitDeliveryFailed': 'Delivery failed — not confirmed',
  'taskView.gitDeliveryShowAll': 'Show all',
  'taskView.gitDeliveryCollapse': 'Collapse',
}

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string, params?: Record<string, string | number>) => {
      let text = messages[key] ?? key
      if (params) {
        for (const [name, value] of Object.entries(params)) {
          text = text.replaceAll(`{${name}}`, String(value))
        }
      }
      return text
    },
  }),
}))

vi.mock('../api', () => ({
  getTaskPayload: mockGetTaskPayload,
}))

vi.mock('../vendor/mermaid', () => ({
  loadMermaid: vi.fn(async () => ({
    initialize: vi.fn(),
    render: mockMermaidRender,
  })),
}))

vi.mock('@vicons/ionicons5', () => ({
  AlertCircleOutline: iconStub,
  GitBranchOutline: iconStub,
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

describe('TaskResultPanel git delivery', () => {
  function makeGitDelivery(overrides: Partial<TaskGitDelivery> = {}): TaskGitDelivery {
    return {
      schema: 'v1',
      attempt_id: 'att-1',
      branch: 'codify/issue-1',
      start_sha: null,
      start_remote_sha: null,
      head_sha: null,
      commits: [],
      recovered_commits: [],
      diff: null,
      push: null,
      ...overrides,
    }
  }

  function mountGitTask(gd: TaskGitDelivery, taskOverrides: Partial<Task> = {}) {
    return mount(TaskResultPanel, {
      props: {
        task: createMockTask({ id: 12, status: 'completed', git_delivery: gd, ...taskOverrides }),
      },
    })
  }

  it('renders this-task commits with net diff, pushed status, and an MR link', () => {
    const commitUrl = 'https://gitlab.example.com/group/test-project/-/merge_requests/9'
    const wrapper = mountGitTask(makeGitDelivery({
      head_sha: 'abcdef1234567890abcdef1234567890abcdef12',
      commits: [
        { sha: '1111111111111111111111111111111111111111', subject: 'feat: add login flow' },
        { sha: '2222222222222222222222222222222222222222', subject: 'fix: style login page' },
      ],
      diff: {
        additions: 5,
        deletions: 2,
        total: 7,
        new_files: ['Login.vue'],
        modified_files: ['App.vue'],
        deleted_files: [],
      },
      push: {
        status: 'pushed',
        remote_sha: 'abcdef1234567890abcdef1234567890abcdef12',
        error: null,
      },
      commit_url: commitUrl,
    }))
    const text = wrapper.text()

    expect(text).toContain('feat: add login flow')
    expect(text).toContain('fix: style login page')
    expect(text).toContain('+5')
    expect(text).toContain('-2')
    expect(text).toContain('Pushed')
    expect(text).toContain('This task commits')
    expect(text).not.toContain('Recovered delivery')
    expect(text).not.toContain('+0 -0')

    const headLink = wrapper.get('.git-delivery__head a.commit-sha-chip--link')
    expect(headLink.attributes('href')).toBe(commitUrl)
    expect(headLink.text()).toContain('abcdef12')
  })

  it('shows recovered commits separately with an already-on-remote push label', () => {
    const wrapper = mountGitTask(makeGitDelivery({
      head_sha: 'cccccccccccccccccccccccccccccccccccccccc',
      commits: [],
      recovered_commits: [
        { sha: '3333333333333333333333333333333333333333', subject: 'feat: inherited earlier work' },
      ],
      diff: null,
      push: {
        status: 'already_present',
        remote_sha: 'cccccccccccccccccccccccccccccccccccccccc',
        error: null,
      },
    }))
    const text = wrapper.text()

    expect(text).toContain('Recovered delivery')
    expect(text).toContain('feat: inherited earlier work')
    expect(text).toContain('Already on remote')
    expect(text).not.toContain('This task commits')
  })

  it('shows the failed push chip together with the remote error message', () => {
    const wrapper = mountGitTask(makeGitDelivery({
      push: {
        status: 'failed',
        remote_sha: null,
        error: {
          code: 'remote_changed',
          message: 'The remote task branch changed between verification and push.',
        },
      },
    }))
    const text = wrapper.text()

    expect(text).toContain('Delivery failed — not confirmed')
    expect(text).toContain('The remote task branch changed between verification and push.')
    expect(wrapper.find('.git-delivery__push--failed').exists()).toBe(true)
  })

  it('does not fabricate zero change stats when diff stats were not collected', () => {
    const wrapper = mountGitTask(makeGitDelivery({
      commits: [
        { sha: '4444444444444444444444444444444444444444', subject: 'chore: config tweaks' },
      ],
      diff: {
        additions: null,
        deletions: null,
        total: null,
        new_files: [],
        modified_files: [],
        deleted_files: [],
      },
      push: { status: 'pushed', remote_sha: null, error: null },
    }))
    const text = wrapper.text()

    expect(text).toContain('Change stats not collected')
    expect(text).not.toContain('+0')
    expect(text).not.toContain('-0')
  })

  it('collapses more than 10 commit rows behind a show-all toggle', async () => {
    const commits = Array.from({ length: 12 }, (_, i) => ({
      sha: String(i + 1).padStart(40, '0'),
      subject: `bulk change ${i + 1}`,
    }))
    const wrapper = mountGitTask(makeGitDelivery({
      commits,
      push: { status: 'pushed', remote_sha: null, error: null },
    }))

    expect(wrapper.findAll('.git-delivery__commit-row')).toHaveLength(10)
    expect(wrapper.text()).toContain('Show all')
    expect(wrapper.text()).not.toContain('bulk change 11')

    await wrapper.get('.git-delivery__toggle').trigger('click')
    await nextTick()

    expect(wrapper.findAll('.git-delivery__commit-row')).toHaveLength(12)
    expect(wrapper.text()).toContain('bulk change 12')
    expect(wrapper.text()).toContain('Collapse')
  })

  it('shows the delivery branch from git_delivery', () => {
    const wrapper = mountGitTask(makeGitDelivery({
      head_sha: 'a'.repeat(40),
      commits: [{ sha: 'a'.repeat(40), subject: 'work' }],
      push: { status: 'pushed', remote_sha: 'a'.repeat(40), error: null },
    }))
    expect(wrapper.text()).toContain('codify/issue-1')
  })

  it('keeps the legacy single-SHA rendering when git_delivery is absent', () => {
    const fullSha = 'abcdef1234567890abcdef1234567890abcdef12'
    const wrapper = mount(TaskResultPanel, {
      props: {
        task: createMockTask({
          id: 12,
          status: 'completed',
          commit_sha: fullSha,
          commit_message: 'legacy summary commit',
          additions: 12,
          deletions: 3,
        }),
      },
    })
    const text = wrapper.text()

    expect(wrapper.find('.git-delivery').exists()).toBe(false)
    expect(wrapper.get('.commit-sha-chip--link').attributes('href')).toBe(
      'https://gitlab.example.com/group/test-project/-/commit/' + fullSha
    )
    expect(text).toContain('abcdef12')
    expect(text).toContain('legacy summary commit')
    expect(text).toContain('+12')
    expect(text).toContain('-3')
  })
})
