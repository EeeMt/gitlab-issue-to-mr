import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import Analytics from './Analytics.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------

const { mockApi, resetMockApi } = vi.hoisted(() => {
  const mock = {
    getAnalytics: vi.fn(),
    getProjects: vi.fn()
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  return { mockApi: mock, resetMockApi }
})

vi.mock('../api', () => ({
  getAnalytics: mockApi.getAnalytics,
  getProjects: mockApi.getProjects
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeLocal: vi.fn((v: any) => `date:${v}`),
  formatMonthDayLocal: vi.fn((v: any) => `monthday:${v}`)
}))

vi.mock('../i18n', () => ({
  currentLocale: ref('en')
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' },
    d: vi.fn((value: unknown) => String(value)),
    n: vi.fn((value: number) => String(value)),
    te: vi.fn((_key: string) => false)
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: ref(1200) }))
}))

vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin--loading' : 'n-spin' }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size'],
    setup(_p: any, { slots }: any) { return () => h('div', slots.default?.()) }
  },
  NButton: {
    name: 'NButton',
    props: ['loading', 'type'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', { class: 'n-button', onClick: () => emit('click') }, slots.default?.())
    }
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'loading', 'placeholder', 'clearable', 'filterable'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-grid' }, slots.default?.()) }
  },
  NGi: {
    name: 'NGi',
    props: [],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-gi' }, slots.default?.()) }
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'rowKey', 'bordered', 'scrollX', 'pagination'],
    setup() { return () => h('div', { class: 'n-data-table' }) }
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-tag' }, slots.default?.()) }
  },
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }),
  NModal: {
    name: 'NModal',
    props: ['preset', 'title', 'show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-modal' }, slots.default?.()) : h('div')
    }
  },
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'size'],
    emits: ['update:value'],
    setup(props: any, { slots, emit }: any) {
      return () => h('div', { class: 'n-tabs', 'data-value': props.value }, [
        h('button', {
          class: 'n-tabs__trigger',
          'data-tab': 'project',
          onClick: () => emit('update:value', 'project')
        }, 'project'),
        h('button', {
          class: 'n-tabs__trigger',
          'data-tab': 'initiator',
          onClick: () => emit('update:value', 'initiator')
        }, 'initiator'),
        slots.default?.()
      ])
    }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_props: any) {
      return () => null
    }
  },
  NIcon: {
    name: 'NIcon',
    props: ['component'],
    setup(_props: any) {
      return () => h('i', { class: 'n-icon' })
    }
  }
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------

const mockAnalytics = {
  window_days: 30,
  generated_at: '2026-01-01T00:00:00Z',
  summary: {
    total_tasks: 42,
    success_rate: 0.857,
    finished_tasks: 35,
    completed_tasks: 30,
    failed_tasks: 4,
    cancelled_tasks: 1,
    avg_execution_seconds: 125.5,
    max_execution_seconds: 600,
    avg_queue_wait_seconds: 5.2,
    max_queue_wait_seconds: 30,
    total_changes: 1500,
    total_additions: 1000,
    total_deletions: 500,
    total_tokens: 50000,
    total_input_tokens: 30000,
    total_output_tokens: 20000,
    avg_total_tokens_per_tracked_task: 1200,
    max_total_tokens_per_tracked_task: 5000,
    token_tracked_tasks: 40,
    tracked_initiator_tasks: 38,
    initiator_tracking_started_at: '2026-01-01T00:00:00Z'
  },
  available_initiators: [
    { initiator_username: 'alice', task_count: 20 },
    { initiator_username: 'bob', task_count: 22 }
  ],
  projects: [],
  initiators: [],
  issue_status_breakdown: [
    { status: 'open', count: 3, share: 0.5 },
    { status: 'in_progress', count: 1, share: 0.1667 },
    { status: 'in_review', count: 1, share: 0.1667 },
    { status: 'closed', count: 1, share: 0.1667 }
  ],
  task_status_breakdown: [
    { status: 'pending', count: 2, share: 0.2 },
    { status: 'queued', count: 1, share: 0.1 },
    { status: 'running', count: 1, share: 0.1 },
    { status: 'completed', count: 4, share: 0.4 },
    { status: 'failed', count: 1, share: 0.1 },
    { status: 'cancelled', count: 1, share: 0.1 }
  ],
  trends: [],
  priority_waits: [],
  error_breakdown: []
}

const mockProjects = [
  { id: 1, name: 'Project A', path_with_namespace: 'group/project-a' },
  { id: 2, name: 'Project B', path_with_namespace: 'group/project-b' }
]

const mockAnalyticsEmptyStatus = {
  ...mockAnalytics,
  issue_status_breakdown: [
    { status: 'open', count: 0, share: 0 },
    { status: 'in_progress', count: 0, share: 0 },
    { status: 'in_review', count: 0, share: 0 },
    { status: 'closed', count: 0, share: 0 }
  ],
  task_status_breakdown: [
    { status: 'pending', count: 0, share: 0 },
    { status: 'queued', count: 0, share: 0 },
    { status: 'running', count: 0, share: 0 },
    { status: 'completed', count: 0, share: 0 },
    { status: 'failed', count: 0, share: 0 },
    { status: 'cancelled', count: 0, share: 0 }
  ]
}

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const mountOptions = {
  global: {
    stubs: {
      PageHeader: {
        template: '<div class="page-header"><slot name="actions"/></div>'
      },
      SummaryCard: {
        props: ['label', 'value', 'note', 'cardClass', 'labelClass', 'valueClass', 'noteClass'],
        template: '<div class="summary-card"><span class="label">{{ label }}</span><span class="value">{{ value }}</span></div>'
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('Analytics', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalytics)
    ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  it('calls getAnalytics and getProjects on mount', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(mockApi.getAnalytics).toHaveBeenCalledTimes(1)
    expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
  })

  it('shows loading state during initial fetch', async () => {
    let resolveAnalytics!: (value: any) => void
    ;(mockApi.getAnalytics as Mock).mockReturnValue(new Promise(r => { resolveAnalytics = r }))
    ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)

    wrapper = mount(Analytics, mountOptions)

    // Synchronous part of fetchAnalytics has set loading = true before the await
    expect(wrapper.vm.loading).toBe(true)
    expect(wrapper.vm.initialLoading).toBe(true)

    resolveAnalytics(mockAnalytics)
    await flushPromises()

    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.initialLoading).toBe(false)
  })

  it('shows summary cards after data loads', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.findAll('.summary-card').length).toBeGreaterThan(0)
  })

  it('summary items computed correctly from analytics data', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    expect(items).toHaveLength(9)
    // First item: Issues (issueTotal = 0, getStats not mocked)
    expect(items[0].value).toBe('0')
    // Second item: total_tasks = 42
    expect(items[1].value).toBe('42')
    // Third item: success_rate = 0.857 → 85.7%
    expect(items[2].value).toBe('85.7%')
    // Sixth item: total_changes = 1500
    expect(items[5].value).toBe('1500')
  })

  it('does not show summary when hasLoadedOnce is false', async () => {
    let resolveAnalytics!: (value: any) => void
    ;(mockApi.getAnalytics as Mock).mockReturnValue(new Promise(r => { resolveAnalytics = r }))

    wrapper = mount(Analytics, mountOptions)
    await nextTick()

    expect(wrapper.vm.hasLoadedOnce).toBe(false)
    expect(wrapper.findAll('.summary-card').length).toBe(0)

    // Resolve to confirm it appears after loading
    resolveAnalytics(mockAnalytics)
    await flushPromises()

    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.findAll('.summary-card').length).toBeGreaterThan(0)
  })

  it('handles getAnalytics error gracefully', async () => {
    ;(mockApi.getAnalytics as Mock).mockRejectedValue(new Error('API Error'))
    ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)

    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    // hasLoadedOnce is set in the finally block — should be true even on error
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.analytics).toBeNull()
  })

  it('refetches when windowDays changes', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    // Clear after the initial call
    ;(mockApi.getAnalytics as Mock).mockClear()

    wrapper.vm.windowDays = 7
    await nextTick()
    await flushPromises()

    expect(mockApi.getAnalytics).toHaveBeenCalledTimes(1)
    expect(mockApi.getAnalytics).toHaveBeenCalledWith(7, null, null)
  })

  it('refetches when selectedInitiatorUsername changes', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    ;(mockApi.getAnalytics as Mock).mockClear()

    wrapper.vm.selectedInitiatorUsername = 'alice'
    await nextTick()
    await flushPromises()

    expect(mockApi.getAnalytics).toHaveBeenCalledTimes(1)
    expect(mockApi.getAnalytics).toHaveBeenCalledWith(30, null, 'alice')
  })

  it('initiatorOptions computed from available_initiators', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    const options = wrapper.vm.initiatorOptions as any[]
    expect(options).toHaveLength(2)
    expect(options[0]).toEqual({ label: 'alice (20)', value: 'alice' })
    expect(options[1]).toEqual({ label: 'bob (22)', value: 'bob' })
  })

  it('refresh button triggers fetchAnalytics', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    ;(mockApi.getAnalytics as Mock).mockClear()

    await wrapper.find('button.n-button').trigger('click')
    await flushPromises()

    expect(mockApi.getAnalytics).toHaveBeenCalledTimes(1)
  })

  it('defaults the merged breakdown card to the project tab', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.vm.analyticsBreakdownTab).toBe('project')
    expect(wrapper.vm.analyticsBreakdownTitle).toBe('analytics.byProject')
    expect(wrapper.find('[data-testid="analytics-breakdown-card"]').exists()).toBe(true)
  })

  it('switches the merged breakdown card to the initiator tab', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="initiator"]').trigger('click')
    await nextTick()

    expect(wrapper.vm.analyticsBreakdownTab).toBe('initiator')
    expect(wrapper.vm.analyticsBreakdownTitle).toBe('analytics.byInitiator')
    expect(wrapper.vm.analyticsBreakdownData).toEqual([])
  })

  it('renders status distribution cards with independent default chart modes', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.find('[data-testid="analytics-issue-status-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="analytics-task-status-card"]').exists()).toBe(true)
    expect(wrapper.vm.issueStatusChartMode).toBe('bar')
    expect(wrapper.vm.taskStatusChartMode).toBe('bar')
  })

  it('switches task status chart mode without changing issue status chart mode', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-testid="task-status-chart-mode-donut"]').trigger('click')
    await nextTick()

    expect(wrapper.vm.taskStatusChartMode).toBe('donut')
    expect(wrapper.vm.issueStatusChartMode).toBe('bar')
  })

  it('renders the status distribution cards before the trend charts', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    const cardTexts = wrapper.findAll('.n-card').map((card) => card.text())
    const issueCardIndex = cardTexts.findIndex((text) => text.includes('analytics.issueStatusDistribution'))
    const taskCardIndex = cardTexts.findIndex((text) => text.includes('analytics.taskStatusDistribution'))
    const trendCardIndex = cardTexts.findIndex((text) => text.includes('analytics.taskVolumeTrend'))

    expect(issueCardIndex).toBeGreaterThan(-1)
    expect(taskCardIndex).toBeGreaterThan(-1)
    expect(trendCardIndex).toBeGreaterThan(-1)
    expect(issueCardIndex).toBeLessThan(trendCardIndex)
    expect(taskCardIndex).toBeLessThan(trendCardIndex)
  })

  it('shows whole-card empty states when both status distributions have no data', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyStatus)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.text()).toContain('analytics.issueStatusDistributionEmpty')
    expect(wrapper.text()).toContain('analytics.taskStatusDistributionEmpty')
    expect(wrapper.findAll('.status-chart__bar-row')).toHaveLength(0)

    // Controls should still exist even when charts are empty
    const issueBarBtn = wrapper.find('[data-testid="issue-status-chart-mode-bar"]')
    const issueDonutBtn = wrapper.find('[data-testid="issue-status-chart-mode-donut"]')
    const taskBarBtn = wrapper.find('[data-testid="task-status-chart-mode-bar"]')
    const taskDonutBtn = wrapper.find('[data-testid="task-status-chart-mode-donut"]')

    expect(issueBarBtn.exists()).toBe(true)
    expect(issueDonutBtn.exists()).toBe(true)
    expect(taskBarBtn.exists()).toBe(true)
    expect(taskDonutBtn.exists()).toBe(true)

    // All toggles should be disabled when there's no data
    expect(issueBarBtn.element.hasAttribute('disabled')).toBe(true)
    expect(issueDonutBtn.element.hasAttribute('disabled')).toBe(true)
    expect(taskBarBtn.element.hasAttribute('disabled')).toBe(true)
    expect(taskDonutBtn.element.hasAttribute('disabled')).toBe(true)
  })
})
