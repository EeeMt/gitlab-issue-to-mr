import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Dashboard from './Dashboard.vue'
import { createMockTask } from '../test/mocks/api'
import type { Issue, Task } from '../api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getIssues: vi.fn<() => Promise<any>>(),
    getTasksPaginated: vi.fn<() => Promise<any>>(),
    getStats: vi.fn<() => Promise<any>>(),
    getActivityHeatmap: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
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

// ---------------------------------------------------------------------------
// Naive-UI stubs
// ---------------------------------------------------------------------------
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
  NButton: {
    name: 'NButton',
    props: ['type', 'disabled', 'loading', 'text'],
    setup(_p: any, { slots }: any) {
      return () => h('button', { class: 'n-button' }, slots.default?.())
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size', 'title'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    },
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'row-key', 'row-props', 'bordered'],
    setup(props: any) {
      return () =>
        h(
          'div',
          { class: 'n-data-table' },
          props.data?.map((row: any) =>
            h('div', { class: 'n-data-table-row', 'data-id': row.id }),
          ),
        )
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
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) {
      return () => h('span', { class: 'n-tag' }, slots.default?.())
    },
  },
  NIcon: {
    name: 'NIcon',
    props: ['size', 'color', 'component'],
    setup(_p: any, { slots }: any) {
      return () => h('i', { class: 'n-icon' }, slots.default?.())
    },
  },
  useMessage: () => mockMessage,
}))

// ---------------------------------------------------------------------------
// Child component stubs
// ---------------------------------------------------------------------------
vi.mock('../components/StatCard.vue', () => ({
  default: {
    name: 'StatCard',
    props: ['label', 'value', 'icon', 'color', 'suffix'],
    setup(props: any) {
      return () =>
        h(
          'div',
          {
            class: 'dashboard-summary-card',
            'data-testid': 'dashboard-summary-card',
            'data-label': props.label,
            'data-value': String(props.value),
          },
          `${props.value}${props.suffix || ''}`,
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

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/tasks/:id', name: 'TaskView', component: { template: '<div>task</div>' } },
    { path: '/issues/:id', name: 'IssueView', component: { template: '<div>issue</div>' } },
    { path: '/issues/create', name: 'CreateIssue', component: { template: '<div>create</div>' } },
  ],
})

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
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

const mockRunningTasks = [
  createMockTask({ id: 10, status: 'running', user_prompt: 'Fix CSS', started_at: '2026-01-01T10:00:00Z' }),
]
const mockQueuedTasks = [
  createMockTask({ id: 20, status: 'queued', user_prompt: 'Add tests', priority: 2 }),
]
const mockCompletedTasks = [
  createMockTask({ id: 30, status: 'completed', user_prompt: 'Refactor', completed_at: '2024-01-10T09:00:00Z' }),
]
const mockFailedTasks = [
  createMockTask({ id: 40, status: 'failed', user_prompt: 'Deploy v2', completed_at: '2024-01-10T08:00:00Z' }),
]

const mockStats = {
  total: 50, pending: 0, queued: 1, running: 3, completed: 30, failed: 10,
  cancelled: 0, completed_24h: 2, failed_cancelled_24h: 1, running_long_30min: 0,
  issues: { total: 15, by_status: { open: 5, in_progress: 3, completed: 6, closed: 1 } },
}

const mockHeatmapData = [{ date: '2024-01-01', count: 3 }]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setupDefaultMocks() {
  mockApi.getIssues.mockResolvedValue({ items: mockIssues, total: mockIssues.length, page: 1, page_size: 5 })
  mockApi.getStats.mockResolvedValue(mockStats)
  mockApi.getActivityHeatmap.mockResolvedValue(mockHeatmapData)
  mockApi.getTasksPaginated.mockImplementation((params: any) => {
    if (params.status === 'running') return Promise.resolve({ items: mockRunningTasks, total: 1, page: 1, page_size: 10 })
    if (params.status === 'queued') return Promise.resolve({ items: mockQueuedTasks, total: 1, page: 1, page_size: 10 })
    if (params.status === 'completed') return Promise.resolve({ items: mockCompletedTasks, total: 1, page: 1, page_size: 5 })
    if (params.status === 'failed') return Promise.resolve({ items: mockFailedTasks, total: 1, page: 1, page_size: 5 })
    return Promise.resolve({ items: [], total: 0, page: 1, page_size: 10 })
  })
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
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

  // -----------------------------------------------------------------------
  // 1. Basic rendering
  // -----------------------------------------------------------------------
  describe('basic rendering', () => {
    it('renders the dashboard root element', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-page"]').exists()).toBe(true)
    })

    it('shows 5 stat cards after loading', async () => {
      await mountDashboard()
      const cards = wrapper.findAll('[data-testid="dashboard-summary-card"]')
      expect(cards.length).toBe(5)
    })

    it('displays correct stat values', async () => {
      await mountDashboard()
      const cards = wrapper.findAll('[data-testid="dashboard-summary-card"]')
      const values = cards.map(c => c.attributes('data-value'))
      // Issues=15, Open=8 (5+3), Tasks=50, Running=3, SuccessRate=75
      expect(values).toEqual(['15', '8', '50', '3', '75'])
    })

    it('shows recent-issues section', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-recent-issues"]').exists()).toBe(true)
    })

    it('shows running-tasks section', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-running-tasks"]').exists()).toBe(true)
    })

    it('shows activity-heatmap section', async () => {
      await mountDashboard()
      expect(wrapper.find('[data-testid="dashboard-activity-heatmap"]').exists()).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // 2. Initial data fetching
  // -----------------------------------------------------------------------
  describe('initial data fetching', () => {
    it('calls getIssues on mount', async () => {
      await mountDashboard()
      expect(mockApi.getIssues).toHaveBeenCalledWith({ page: 1, page_size: 5 })
    })

    it('calls getTasksPaginated for running and queued', async () => {
      await mountDashboard()
      const calls = mockApi.getTasksPaginated.mock.calls
      expect(calls).toEqual(
        expect.arrayContaining([
          [expect.objectContaining({ status: 'running' })],
          [expect.objectContaining({ status: 'queued' })],
        ]),
      )
    })

    it('calls getStats on mount', async () => {
      await mountDashboard()
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })

    it('calls getActivityHeatmap on mount', async () => {
      await mountDashboard()
      expect(mockApi.getActivityHeatmap).toHaveBeenCalledTimes(1)
    })

    it('populates recentIssues from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.recentIssues).toHaveLength(2)
      expect(wrapper.vm.recentIssues[0].id).toBe(1)
    })

    it('populates stats refs from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.statsIssueTotal).toBe(15)
      expect(wrapper.vm.statsOpenIssues).toBe(8) // open=5 + in_progress=3
      expect(wrapper.vm.statsTotal).toBe(50)
      expect(wrapper.vm.statsRunning).toBe(3)
      expect(wrapper.vm.statsCompleted).toBe(30)
      expect(wrapper.vm.statsFailed).toBe(10)
    })

    it('populates heatmapData from response', async () => {
      await mountDashboard()
      expect(wrapper.vm.heatmapData).toEqual(mockHeatmapData)
    })
  })

  // -----------------------------------------------------------------------
  // 4. successRate computed
  // -----------------------------------------------------------------------
  describe('successRate computed', () => {
    it('returns correct percentage', async () => {
      await mountDashboard()
      // completed=30, failed=10 -> 30/40*100 = 75
      expect(wrapper.vm.successRate).toBe(75)
    })

    it('returns 0 when no completed or failed tasks', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockResolvedValue({ ...mockStats, completed: 0, failed: 0 })
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      expect(wrapper.vm.successRate).toBe(0)
    })

    it('returns 100 when all tasks completed', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockResolvedValue({ ...mockStats, completed: 10, failed: 0 })
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      expect(wrapper.vm.successRate).toBe(100)
    })

    it('rounds to nearest integer', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockResolvedValue({ ...mockStats, completed: 2, failed: 1 })
      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()
      expect(wrapper.vm.successRate).toBe(67)
    })
  })

  // -----------------------------------------------------------------------
  // 5. Row navigation
  // -----------------------------------------------------------------------
  describe('row navigation', () => {
    it('issueRowProps returns cursor style and navigates to /issues/:id', async () => {
      await mountDashboard()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.issueRowProps(mockIssues[0])
      expect(props.style).toBe('cursor: pointer')
      props.onClick()
      expect(pushSpy).toHaveBeenCalledWith('/issues/1')
    })

    it('taskRowProps returns cursor style and navigates to /tasks/:id', async () => {
      await mountDashboard()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.taskRowProps(mockRunningTasks[0])
      expect(props.style).toBe('cursor: pointer')
      props.onClick()
      expect(pushSpy).toHaveBeenCalledWith('/tasks/10')
    })
  })

  // -----------------------------------------------------------------------
  // 6. Polling
  // -----------------------------------------------------------------------
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

  // -----------------------------------------------------------------------
  // 7. Loading state
  // -----------------------------------------------------------------------
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

      resolveIssues({ items: [], total: 0, page: 1, page_size: 5 })
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

  // -----------------------------------------------------------------------
  // runningAndQueuedTasks computed
  // -----------------------------------------------------------------------
  describe('runningAndQueuedTasks computed', () => {
    it('merges running and queued tasks', async () => {
      await mountDashboard()
      const combined = wrapper.vm.runningAndQueuedTasks as Task[]
      expect(combined).toHaveLength(2)
      expect(combined.map((t: Task) => t.id)).toEqual([10, 20])
    })
  })

  // -----------------------------------------------------------------------
  // Error handling
  // -----------------------------------------------------------------------
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

      expect(wrapper.vm.statsTotal).toBe(0)
      expect(wrapper.vm.statsRunning).toBe(0)
    })

    it('handles heatmap failure silently', async () => {
      setupDefaultMocks()
      mockApi.getActivityHeatmap.mockRejectedValue(new Error('fail'))

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.heatmapData).toEqual([])
    })
  })

  // -----------------------------------------------------------------------
  // fetchData guard
  // -----------------------------------------------------------------------
  describe('fetchData guard', () => {
    it('skips fetch when already loading', async () => {
      setupDefaultMocks()
      let resolveIssues!: (v: any) => void
      mockApi.getIssues.mockReturnValue(new Promise(r => { resolveIssues = r }) as any)

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      const countBefore = mockApi.getIssues.mock.calls.length

      // Second call should be blocked by the loading guard
      wrapper.vm.$forceUpdate()
      await nextTick()
      expect(mockApi.getIssues.mock.calls.length).toBe(countBefore)

      resolveIssues({ items: [], total: 0, page: 1, page_size: 5 })
      await flushPromises()
    })
  })
})
