import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Dashboard from './Dashboard.vue'
import { createMockTask } from '../test/mocks/api'
import type { Issue, Task } from '../api'

const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getIssues: vi.fn<() => Promise<any>>(),
    getTasksPaginated: vi.fn<() => Promise<any>>(),
    getStats: vi.fn<() => Promise<any>>(),
    getActivityHeatmap: vi.fn<() => Promise<any>>(),
    getAnalytics: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

vi.mock('../i18n', () => ({ currentLocale: ref('en') }))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((value: any) => `formatted-${value}`),
}))

vi.mock('../utils/format', () => ({
  formatPriority: vi.fn((v: any) => `P${v ?? '-'}`),
}))

vi.mock('../api', () => ({
  getIssues: mockApi.getIssues,
  getTasksPaginated: mockApi.getTasksPaginated,
  getStats: mockApi.getStats,
  getActivityHeatmap: mockApi.getActivityHeatmap,
  getAnalytics: mockApi.getAnalytics,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' },
    d: vi.fn((value: unknown) => String(value)),
    n: vi.fn((value: number) => String(value)),
    te: vi.fn(() => false),
  }),
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } })),
}))

vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () =>
        props.show
          ? h('div', { class: 'n-spin-loading' }, slots.default?.())
          : h('div', { class: 'n-spin' }, slots.default?.())
    },
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size', 'title'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    },
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'x-gap', 'y-gap'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
  },
  NGi: {
    name: 'NGi',
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
  },
  NIcon: {
    name: 'NIcon',
    props: ['size', 'color', 'component'],
    setup(_p: any, { slots }: any) {
      return () => h('i', { class: 'n-icon' }, slots.default?.())
    },
  },
  NTooltip: {
    name: 'NTooltip',
    props: ['trigger'],
    setup(_p: any, { slots }: any) {
      return () => h('span', { class: 'n-tooltip' }, [slots.trigger?.(), slots.default?.()])
    },
  },
  useMessage: () => mockMessage,
}))

vi.mock('../components/StatusPieChart.vue', () => ({
  default: {
    name: 'StatusPieChart',
    props: ['data'],
    setup() {
      return () =>
        h(
          'div',
          {
            class: 'status-pie-chart',
            'data-testid': 'status-pie-chart',
          },
          'PieChart',
        )
    },
  },
}))

vi.mock('../components/ActivityHeatmap.vue', () => ({
  default: {
    name: 'ActivityHeatmap',
    props: ['data'],
    setup() {
      return () => h('div', { class: 'activity-heatmap', 'data-testid': 'activity-heatmap' })
    },
  },
}))

vi.mock('../components/TrendChart.vue', () => ({
  default: {
    name: 'TrendChart',
    props: ['data'],
    setup() {
      return () => h('div', { class: 'trend-chart', 'data-testid': 'trend-chart' })
    },
  },
}))

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/tasks/:id', name: 'TaskView', component: { template: '<div>task</div>' } },
    { path: '/issues/:id', name: 'IssueView', component: { template: '<div>issue</div>' } },
    { path: '/issues/create', name: 'CreateIssue', component: { template: '<div>create</div>' } },
  ],
})

const mockIssues: Issue[] = [
  {
    id: 1, title: 'Bug: login broken', description: null, project_id: 1, status: 'open',
    branch_name: null, base_branch: null, target_branch: null, merge_request_iid: null,
    merge_request_url: null, claude_session_id: null, initiator_user_id: null,
    initiator_username: null, created_at: '2024-01-01T10:00:00Z',
    updated_at: '2024-01-01T10:00:00Z', task_count: 3,
  },
  {
    id: 2, title: 'Feature: dark mode', description: null, project_id: 1, status: 'in_progress',
    branch_name: null, base_branch: null, target_branch: null, merge_request_iid: null,
    merge_request_url: null, claude_session_id: null, initiator_user_id: null,
    initiator_username: null, created_at: '2024-01-02T10:00:00Z',
    updated_at: '2024-01-02T10:00:00Z', task_count: 1,
  },
]

const mockBoardTasks: Task[] = [
  createMockTask({ id: 10, status: 'running', user_prompt: 'Fix CSS', started_at: '2026-01-01T10:00:00Z' }),
  createMockTask({ id: 20, status: 'queued', user_prompt: 'Add tests', priority: 2 }),
  createMockTask({ id: 30, status: 'completed', user_prompt: 'Refactor', completed_at: '2024-01-10T09:00:00Z' }),
  createMockTask({ id: 40, status: 'failed', user_prompt: 'Deploy v2', completed_at: '2024-01-10T08:00:00Z' }),
]

const longPrompt = 'A'.repeat(180)

const mockStats = {
  total: 50, pending: 0, queued: 1, running: 3, completed: 30, failed: 10,
  cancelled: 0, completed_24h: 2, failed_cancelled_24h: 1, running_long_30min: 0,
  issues: { total: 15, by_status: { open: 5, in_progress: 3, in_review: 6, closed: 1 } },
}

const mockHeatmapData = [{ date: '2024-01-01', count: 3 }]

const mockAnalyticsResponse = {
  window_days: 365,
  generated_at: '2024-01-10T00:00:00Z',
  summary: {
    total_tasks: 50, total_additions: 1234, total_deletions: 567, total_changes: 1801,
    total_input_tokens: 50000, total_output_tokens: 30000, total_tokens: 80000,
    completed_tasks: 30, failed_tasks: 10, cancelled_tasks: 0, finished_tasks: 40,
    success_rate: 75, failure_rate: 25, tracked_initiator_tasks: 50, token_tracked_tasks: 40,
    initiator_tracking_started_at: null, avg_execution_seconds: null, max_execution_seconds: null,
    avg_queue_wait_seconds: null, max_queue_wait_seconds: null,
    avg_total_tokens_per_tracked_task: null, max_total_tokens_per_tracked_task: null,
  },
  available_initiators: [], projects: [], initiators: [], trends: [], priority_waits: [], error_breakdown: [],
}

function setupDefaultMocks() {
  mockApi.getIssues.mockResolvedValue({ items: mockIssues, total: mockIssues.length, page: 1, page_size: 100 })
  mockApi.getStats.mockResolvedValue(mockStats)
  mockApi.getActivityHeatmap.mockResolvedValue(mockHeatmapData)
  mockApi.getAnalytics.mockResolvedValue(mockAnalyticsResponse)
  mockApi.getTasksPaginated.mockResolvedValue({ items: mockBoardTasks, total: mockBoardTasks.length, page: 1, page_size: 100 })
}

describe('Dashboard', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    router.push('/')
    await router.isReady()

    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    })

    vi.spyOn(globalThis, 'setInterval').mockImplementation(
      () => 1 as unknown as ReturnType<typeof setInterval>,
    )
    vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => undefined)
    Object.values(mockMessage).forEach(fn => fn.mockReset())
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
    vi.restoreAllMocks()
  })

  async function mountDashboard() {
    setupDefaultMocks()
    wrapper = mount(Dashboard, { global: { plugins: [router] } })
    await flushPromises()
    await nextTick()
    return wrapper
  }

  describe('basic rendering', () => {
    it('renders the dashboard root element', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-page"]').exists()).toBe(true)
    })

    it('shows 4 summary cards after loading', async () => {
      await mountDashboard()
      const cards = wrapper.findAll('[data-testid="dashboard-summary-card"]')
      expect(cards.length).toBe(4)
    })

    it('renders pie charts and stat cards', async () => {
      await mountDashboard()
      const pieCharts = wrapper.findAll('[data-testid="status-pie-chart"]')
      expect(pieCharts.length).toBe(2)
      const titles = wrapper.findAll('.metric-title')
      expect(titles.length).toBeGreaterThanOrEqual(4)
      expect(titles[0].text()).toContain('dashboard.issueStatus')
      expect(titles[1].text()).toContain('dashboard.taskStatus')
    })

    it('renders my work board instead of recent issues and running sections', async () => {
      await mountDashboard()

      expect(wrapper.find('[data-testid="dashboard-my-work-board"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="dashboard-recent-issues"]').exists()).toBe(false)
      expect(wrapper.find('[data-testid="dashboard-running-tasks"]').exists()).toBe(false)
    })

    it('shows activity-heatmap section', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-activity-heatmap"]').exists()).toBe(true)
    })
  })

  describe('initial data fetching', () => {
    it('calls getIssues on mount', async () => {
      await mountDashboard()
      expect(mockApi.getIssues).toHaveBeenCalledWith({ page: 1, page_size: 100 })
    })

    it('calls getTasksPaginated once for board tasks', async () => {
      await mountDashboard()
      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({ page: 1, page_size: 100 })
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)
    })

    it('calls getStats on mount', async () => {
      await mountDashboard()
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })

    it('calls getActivityHeatmap on mount', async () => {
      await mountDashboard()
      expect(mockApi.getActivityHeatmap).toHaveBeenCalledTimes(1)
    })

    it('populates boardIssues from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.boardIssues).toHaveLength(2)
      expect(wrapper.vm.boardIssues[0].id).toBe(1)
    })

    it('populates boardTasks from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.boardTasks).toHaveLength(4)
      expect(wrapper.vm.boardTasks[0].id).toBe(10)
    })

    it('populates stats refs from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.statsPending).toBe(0)
      expect(wrapper.vm.statsQueued).toBe(1)
      expect(wrapper.vm.statsRunning).toBe(3)
      expect(wrapper.vm.statsCompleted).toBe(30)
      expect(wrapper.vm.statsFailed).toBe(10)
    })

    it('populates analytics refs from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.analyticsTotalAdditions).toBe(1234)
      expect(wrapper.vm.analyticsTotalDeletions).toBe(567)
      expect(wrapper.vm.analyticsTotalTokens).toBe(80000)
    })

    it('populates heatmapData from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.heatmapData).toEqual(mockHeatmapData)
    })
  })

  describe('my work board', () => {
    it('defaults to the issues tab', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="my-work-board-tab-issues"]').attributes('data-active')).toBe('true')
    })

    it('groups issues into issue status columns', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="issue-column-open"]').text()).toContain('#1')
      expect(wrapper.find('[data-testid="issue-column-in_progress"]').text()).toContain('#2')
      expect(wrapper.find('[data-testid="issue-column-in_review"]').text()).toContain('dashboard.myWorkBoard.emptyColumn')
      expect(wrapper.find('[data-testid="issue-column-closed"]').text()).toContain('dashboard.myWorkBoard.emptyColumn')
    })

    it('switches to the tasks tab and shows task status columns', async () => {
      await mountDashboard()
      await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
      await nextTick()

      expect(wrapper.find('[data-testid="task-column-running"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-column-queued"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-column-pending"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-column-completed"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-column-failed"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-column-cancelled"]').exists()).toBe(true)
    })

    it('keeps empty columns visible with empty text', async () => {
      setupDefaultMocks()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 100 })

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
      await nextTick()
      await wrapper.find('[data-testid="my-work-board-tab-issues"]').trigger('click')
      await nextTick()

      expect(wrapper.find('[data-testid="issue-column-open"]').text()).toContain('dashboard.myWorkBoard.emptyColumn')
      expect(wrapper.find('[data-testid="my-work-board-empty-issues"]').exists()).toBe(true)
    })

    it('shows a notice when the board only displays the first 100 tasks', async () => {
      setupDefaultMocks()
      mockApi.getTasksPaginated.mockResolvedValue({ items: mockBoardTasks, total: 145, page: 1, page_size: 100 })

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
      await nextTick()

      expect(wrapper.find('[data-testid="my-work-board-notice-tasks"]').text()).toContain('dashboard.myWorkBoard.limitNotice')
    })

    it('truncates long task prompt text in task cards', async () => {
      setupDefaultMocks()
      mockApi.getTasksPaginated.mockResolvedValue({
        items: [createMockTask({ id: 10, status: 'running', user_prompt: longPrompt })],
        total: 1,
        page: 1,
        page_size: 100,
      })

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
      await nextTick()

      const card = wrapper.find('[data-testid="task-card-10"]')
      expect(card.text()).toContain(longPrompt)
      expect(card.attributes('title')).toBe(longPrompt)
    })

    it('navigates to issue detail when an issue card is clicked', async () => {
      await mountDashboard()
      await wrapper.find('[data-testid="issue-card-1"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/issues/1')
    })

    it('navigates to task detail when a task card is clicked', async () => {
      await mountDashboard()
      await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
      await nextTick()
      await wrapper.find('[data-testid="task-card-10"]').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.fullPath).toBe('/tasks/10')
    })
  })

  describe('chart data computed', () => {
    it('issueChartData filters out zero-value entries', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockResolvedValue({
        ...mockStats,
        issues: { total: 5, by_status: { open: 5, in_progress: 0, in_review: 0, closed: 0 } },
      })
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      const data = wrapper.vm.issueChartData
      expect(data.length).toBe(1)
      expect(data[0].value).toBe(5)
    })

    it('taskChartData includes all non-zero statuses', async () => {
      await mountDashboard()
      const data = wrapper.vm.taskChartData
      expect(data.length).toBe(4)
    })

    it('formatNumber abbreviates thousands', async () => {
      await mountDashboard()
      expect(wrapper.vm.$.setupState.formatNumber(1500)).toBe('1.5K')
      expect(wrapper.vm.$.setupState.formatNumber(2_500_000)).toBe('2.5M')
      expect(wrapper.vm.$.setupState.formatNumber(42)).toBe('42')
    })
  })

  describe('polling', () => {
    it('sets up a 15-second interval', async () => {
      await mountDashboard()
      expect(globalThis.setInterval).toHaveBeenCalledWith(expect.any(Function), 15_000)
    })

    it('clears interval on unmount', async () => {
      await mountDashboard()
      wrapper.unmount()
      await nextTick()
      expect(globalThis.clearInterval).toHaveBeenCalled()
    })

    it('refreshes data on each polling tick', async () => {
      vi.restoreAllMocks()
      vi.useFakeTimers()

      setupDefaultMocks()
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      const callsBefore = mockApi.getIssues.mock.calls.length

      vi.advanceTimersByTime(15_000)
      await flushPromises()

      expect(mockApi.getIssues.mock.calls.length).toBeGreaterThan(callsBefore)

      vi.useRealTimers()
    })

    it('skips polling when tab is hidden', async () => {
      vi.restoreAllMocks()
      vi.useFakeTimers()

      setupDefaultMocks()
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      const callsBefore = mockApi.getIssues.mock.calls.length

      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden', writable: true, configurable: true,
      })
      vi.advanceTimersByTime(15_000)
      await flushPromises()

      expect(mockApi.getIssues.mock.calls.length).toBe(callsBefore)

      vi.useRealTimers()
    })
  })

  describe('loading state', () => {
    it('initialLoading is true before first fetch completes', async () => {
      let resolveIssues!: (v: any) => void
      const pending = new Promise(r => { resolveIssues = r })

      setupDefaultMocks()
      mockApi.getIssues.mockReturnValue(pending as any)

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(true)
      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.hasLoadedOnce).toBe(false)

      resolveIssues({ items: [], total: 0, page: 1, page_size: 100 })
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(false)
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('initialLoading is false after first load completes', async () => {
      await mountDashboard()
      expect(wrapper.vm.initialLoading).toBe(false)
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })
  })

  describe('error handling', () => {
    it('shows error message when main fetch fails', async () => {
      setupDefaultMocks()
      mockApi.getIssues.mockRejectedValue(new Error('Network error'))

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      expect(mockMessage.error).toHaveBeenCalledWith('dashboard.failedToFetchTasks')
    })

    it('handles stats failure silently', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockRejectedValue(new Error('Stats down'))

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.statsRunning).toBe(0)
      expect(wrapper.vm.statsCompleted).toBe(0)
    })

    it('handles analytics failure silently', async () => {
      setupDefaultMocks()
      mockApi.getAnalytics.mockRejectedValue(new Error('Analytics down'))

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.analyticsTotalTokens).toBe(0)
    })

    it('handles heatmap failure silently', async () => {
      setupDefaultMocks()
      mockApi.getActivityHeatmap.mockRejectedValue(new Error('fail'))

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.heatmapData).toEqual([])
    })
  })

  describe('fetchData guard', () => {
    it('skips fetch when already loading', async () => {
      setupDefaultMocks()
      let resolveIssues!: (v: any) => void
      mockApi.getIssues.mockReturnValue(new Promise(r => { resolveIssues = r }) as any)

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      const countBefore = mockApi.getIssues.mock.calls.length

      wrapper.vm.$forceUpdate()
      await nextTick()
      expect(mockApi.getIssues.mock.calls.length).toBe(countBefore)

      resolveIssues({ items: [], total: 0, page: 1, page_size: 100 })
      await flushPromises()
    })
  })
})
