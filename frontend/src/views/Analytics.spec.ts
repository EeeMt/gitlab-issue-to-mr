import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import type { AnalyticsResponse } from '../api'
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
    t: vi.fn((key: string) => ({
      'analytics.issueStatusDistributionEmpty': 'No issues match the current filters and time window yet.',
      'analytics.taskStatusDistributionEmpty': 'No tasks match the current filters and time window yet.',
      'analytics.providersEmpty': 'No provider analytics match the current filters and time window yet.'
    }[key] ?? key)),
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
    setup(props: any) {
      return () => h('div', { class: 'n-data-table' }, (props.data || []).map((row: any, index: number) =>
        h('div', { class: 'n-data-table__row', 'data-row-index': String(index) },
          props.columns?.map((column: any) => {
            const cellContent = column.render ? column.render(row, index) : row[column.key]
            return h('div', { class: 'n-data-table__cell', 'data-column-key': column.key }, cellContent == null ? '' : String(cellContent))
          }) || []
        )
      ))
    }
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
      return () => {
        const defaultChildren = slots.default?.() ?? []
        const tabPanes = defaultChildren.filter((child: any) => child?.type?.name === 'NTabPane')
        const tabButtons = tabPanes.map((pane: any) => {
          const tabName = pane.props?.name
          const tabLabel = pane.props?.tab ?? String(tabName)
          return h('button', {
            class: 'n-tabs__trigger',
            'data-tab': String(tabName),
            onClick: () => emit('update:value', tabName)
          }, String(tabLabel))
        })
        const activePane = tabPanes.find((pane: any) => pane.props?.name === props.value)

        return h('div', { class: 'n-tabs', 'data-value': props.value }, [
          ...tabButtons,
          activePane ? h('div', { class: 'n-tabs__pane', 'data-active-tab': String(props.value) }, [activePane]) : null
        ])
      }
    }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tab-pane' }, slots.default?.())
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

const mockAnalytics: AnalyticsResponse = {
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
  provider_summary: {
    active_provider_count: 2,
    provider_covered_task_count: 40,
    provider_covered_total_tokens: 48000,
    provider_success_rate: 0.85
  },
  available_initiators: [
    { initiator_username: 'alice', task_count: 20, initiator_gitlab_user_id: 101 },
    { initiator_username: 'bob', task_count: 22, initiator_gitlab_user_id: 102 }
  ],
  projects: [],
  initiators: [],
  providers: [
    {
      provider_id: 1,
      provider_name: 'Claude Sonnet',
      provider_model: 'claude-sonnet-4-6',
      task_count: 24,
      completed_task_count: 20,
      failed_task_count: 3,
      cancelled_task_count: 1,
      finished_task_count: 24,
      success_rate: 0.833,
      total_input_tokens: 20000,
      total_output_tokens: 12000,
      total_tokens: 32000,
      avg_tokens_per_task: 1333.3,
      avg_tokens_per_second: 4.2,
      avg_tokens_per_changed_line: 10.4,
      avg_execution_seconds: 300,
      avg_execution_seconds_per_changed_line: 2.4
    },
    {
      provider_id: null,
      provider_name: 'Unknown / Legacy',
      provider_model: null,
      task_count: 16,
      completed_task_count: 10,
      failed_task_count: 1,
      cancelled_task_count: 5,
      finished_task_count: 11,
      success_rate: 0.625,
      total_input_tokens: 10000,
      total_output_tokens: 6000,
      total_tokens: 16000,
      avg_tokens_per_task: 1000,
      avg_tokens_per_second: null,
      avg_tokens_per_changed_line: null,
      avg_execution_seconds: 420,
      avg_execution_seconds_per_changed_line: null
    }
  ],
  provider_chart_series: {
    success_rate: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 0.833 },
      { provider_id: null, label: 'Unknown / Legacy', value: 0.625 }
    ],
    avg_tokens_per_second: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 4.2 }
    ],
    avg_tokens_per_changed_line: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 10.4 }
    ],
    avg_execution_seconds_per_changed_line: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 2.4 }
    ]
  },
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

const mockAnalyticsEmptyProviders: AnalyticsResponse = {
  ...mockAnalytics,
  provider_summary: {
    active_provider_count: 0,
    provider_covered_task_count: 0,
    provider_covered_total_tokens: 0,
    provider_success_rate: null
  },
  providers: [],
  provider_chart_series: {
    success_rate: [],
    avg_tokens_per_second: [],
    avg_tokens_per_changed_line: [],
    avg_execution_seconds_per_changed_line: []
  }
}

const mockAnalyticsEmptyProviderSuccessSeries: AnalyticsResponse = {
  ...mockAnalytics,
  provider_chart_series: {
    ...mockAnalytics.provider_chart_series,
    success_rate: []
  }
}

const mockAnalyticsEmptyProviderEfficiencySeries: AnalyticsResponse = {
  ...mockAnalytics,
  provider_chart_series: {
    ...mockAnalytics.provider_chart_series,
    avg_execution_seconds_per_changed_line: []
  }
}

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

  it('defaults the top-level analytics tab to overview', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.find('[data-tab="overview"]').exists()).toBe(true)
    expect(wrapper.find('[data-tab="providers"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="analytics-breakdown-card"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="analytics-providers-panel"]').exists()).toBe(false)
  })

  it('switches to the providers tab and renders provider analytics content', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="analytics-providers-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('Claude Sonnet')
    expect(wrapper.text()).toContain('claude-sonnet-4-6')
    expect(wrapper.text()).toContain('Unknown / Legacy')
  })

  it('renders the provider empty state when the providers tab has no provider rows', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyProviders)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="analytics-providers-panel"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('No provider analytics match the current filters and time window yet.')
  })

  it('renders N/A for null provider efficiency metrics on the providers tab', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="analytics-providers-panel"]').text()).toContain('N/A')
  })

  it('switches provider efficiency metric mode without changing other provider tab state', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    await wrapper.find('[data-testid="provider-efficiency-metric-seconds-per-line"]').trigger('click')
    await nextTick()

    expect(wrapper.vm.providersEfficiencyMetric).toBe('avg_execution_seconds_per_changed_line')
    expect(wrapper.find('[data-testid="analytics-providers-panel"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="analytics-provider-success-rate-card"]').exists()).toBe(true)
  })

  it('shows a chart empty state when providers exist but success-rate series is empty', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyProviderSuccessSeries)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="analytics-provider-success-rate-card"]').text()).toContain('No provider analytics match the current filters and time window yet.')
    expect(wrapper.text()).toContain('Claude Sonnet')
  })

  it('shows a chart empty state when the selected provider efficiency series is empty', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyProviderEfficiencySeries)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    await wrapper.find('[data-tab="providers"]').trigger('click')
    await nextTick()

    await wrapper.find('[data-testid="provider-efficiency-metric-seconds-per-line"]').trigger('click')
    await nextTick()

    expect(wrapper.find('[data-testid="analytics-providers-panel"]').text()).toContain('No provider analytics match the current filters and time window yet.')
    expect(wrapper.vm.providersEfficiencyMetric).toBe('avg_execution_seconds_per_changed_line')
  })

  it('shows whole-card empty states when both status distributions have no data', async () => {
    ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyStatus)
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    expect(wrapper.text()).toContain('No issues match the current filters and time window yet.')
    expect(wrapper.text()).toContain('No tasks match the current filters and time window yet.')
    expect(wrapper.find('.status-chart--bar').exists()).toBe(false)
    expect(wrapper.find('.status-chart--donut').exists()).toBe(false)
  })

  it('keeps both status cards inside a stable body wrapper across chart modes', async () => {
    wrapper = mount(Analytics, mountOptions)
    await flushPromises()

    const issueCard = wrapper.find('[data-testid="analytics-issue-status-card"]')
    const taskCard = wrapper.find('[data-testid="analytics-task-status-card"]')

    expect(issueCard.find('.analytics-status-card__body').exists()).toBe(true)
    expect(taskCard.find('.analytics-status-card__body').exists()).toBe(true)

    await wrapper.find('[data-testid="issue-status-chart-mode-donut"]').trigger('click')
    await wrapper.find('[data-testid="task-status-chart-mode-donut"]').trigger('click')
    await nextTick()

    expect(issueCard.find('.analytics-status-card__body').exists()).toBe(true)
    expect(taskCard.find('.analytics-status-card__body').exists()).toBe(true)
    expect(issueCard.find('.status-chart--donut').exists()).toBe(true)
    expect(taskCard.find('.status-chart--donut').exists()).toBe(true)
  })
})
