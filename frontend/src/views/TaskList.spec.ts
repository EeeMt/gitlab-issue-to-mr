import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import TaskList from './TaskList.vue'
import { createMockTask, createMockProject } from '../test/mocks/api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const mockIsMobileRef = vi.hoisted(() => ({ value: false }))

const { mockApi, resetMockApi, mockMessage, mockStartPolling, mockStopPolling } = vi.hoisted(() => {
  const mock = {
    getTaskFilterOptions: vi.fn<() => Promise<any>>(),
    getProjects: vi.fn<() => Promise<any>>(),
    getTasksPaginated: vi.fn<() => Promise<any>>(),
    getStats: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return {
    mockApi: mock,
    resetMockApi,
    mockMessage: mockMsg,
    mockStartPolling: vi.fn(),
    mockStopPolling: vi.fn(),
  }
})

const mockFilterState = vi.hoisted(() => ({
  filters: { value: {} },
  sort: { value: { field: 'created_at', order: 'desc' as const } },
  visibleColumns: { value: ['id', 'user_prompt', 'project', 'status', 'priority', 'changes', 'created_at'] },
  apiParams: { value: { sort_by: 'created_at', sort_order: 'desc' } },
  addFilter: vi.fn(),
  removeFilter: vi.fn(),
  clearAllFilters: vi.fn(),
  setSort: vi.fn(),
  resetSort: vi.fn(),
  toggleColumn: vi.fn(),
  resetColumns: vi.fn(),
  activeFilterCount: { value: 0 },
  hasActiveFilters: { value: false },
}))

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../i18n', () => ({ currentLocale: ref('en') }))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((value: any) => `formatted-${value}`),
}))

vi.mock('../utils/format', () => ({
  formatPriority: vi.fn((v: any) => `P${v ?? '-'}`),
  getProjectLabel: vi.fn((task: any, fallback?: string) => task.project_name || fallback || '-'),
}))

vi.mock('../api', () => ({
  getTaskFilterOptions: mockApi.getTaskFilterOptions,
  getProjects: mockApi.getProjects,
  getTasksPaginated: mockApi.getTasksPaginated,
  getStats: mockApi.getStats,
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
    props: ['type', 'disabled', 'loading', 'text', 'secondary', 'onClick'],
    setup(props: any, { slots }: any) {
      return () => h('button', { class: 'n-button', onClick: props.onClick }, slots.default?.())
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
    props: ['columns', 'data', 'loading', 'row-key', 'row-props', 'bordered', 'pagination', 'remote', 'scrollX'],
    setup(props: any) {
      return () =>
        h(
          'div',
          { class: 'n-data-table', 'data-scroll-x': props.scrollX },
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
    props: ['size', 'round', 'type', 'closable'],
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
  DataTableColumns: {},
}))

// ---------------------------------------------------------------------------
// Child component stubs
// ---------------------------------------------------------------------------
vi.mock('../components/filter/FilterToolbar.vue', () => ({
  default: {
    name: 'FilterToolbar',
    props: ['config', 'filters', 'sort', 'visibleColumns', 'activeFilterCount', 'hasActiveFilters', 'resultCount', 'searchPlaceholder', 'searchValue', 'searchMinLength'],
    setup() {
      return () => h('div', { class: 'filter-toolbar-mock', 'data-testid': 'filter-toolbar' })
    },
  },
}))

vi.mock('../components/PageHeader.vue', () => ({
  default: {
    name: 'PageHeader',
    props: ['title', 'subtitle', 'rootClass', 'titleClass', 'subtitleClass', 'actionsClass'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'page-header-mock' }, [slots.actions?.()])
    },
  },
}))

vi.mock('../components/SummaryCard.vue', () => ({
  default: {
    name: 'SummaryCard',
    props: ['label', 'value', 'cardClass', 'labelClass', 'valueClass'],
    setup(props: any) {
      return () => h('div', { class: 'summary-card-mock', 'data-testid': 'summary-card' }, `${props.label}: ${props.value}`)
    },
  },
}))

// ---------------------------------------------------------------------------
// Composable mocks
// ---------------------------------------------------------------------------
vi.mock('../composables/useFilterSort', () => ({
  useFilterSort: () => mockFilterState,
}))

vi.mock('../composables/usePolling', () => ({
  usePolling: () => ({
    start: mockStartPolling,
    stop: mockStopPolling,
    isActive: ref(false),
  }),
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({ isMobile: mockIsMobileRef, isCompact: ref(false), width: ref(1200) }),
}))

// ---------------------------------------------------------------------------
// Icon stubs
// ---------------------------------------------------------------------------
vi.mock('@vicons/ionicons5', () => ({
  EllipseOutline: {},
  FolderOpenOutline: {},
  FlagOutline: {},
  PersonOutline: {},
  CalendarOutline: {},
  GitMergeOutline: {},
  GitNetworkOutline: {},
  TimeOutline: {},
  GridOutline: {},
  CheckmarkCircleOutline: {},
  PlayCircleOutline: {},
}))

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div />' } },
    { path: '/tasks', name: 'TaskList', component: { template: '<div />' } },
    { path: '/tasks/:id', name: 'TaskView', component: { template: '<div />' } },
    { path: '/issues', name: 'IssueList', component: { template: '<div />' } },
    { path: '/issues/:id', name: 'IssueView', component: { template: '<div />' } },
    { path: '/issues/create', name: 'CreateIssue', component: { template: '<div />' } },
  ],
})

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockProjects = [
  createMockProject({ id: 1, name: 'project-1', path_with_namespace: 'group/project-1' }),
  createMockProject({ id: 2, name: 'project-2', path_with_namespace: 'group/project-2' }),
]

const mockTasks = [
  createMockTask({ id: 1, status: 'running', user_prompt: 'Fix CSS', initiator_username: 'alice' }),
  createMockTask({ id: 2, status: 'completed', user_prompt: 'Add tests', initiator_username: 'bob' }),
  createMockTask({ id: 3, status: 'pending', user_prompt: 'Deploy', initiator_username: 'alice' }),
]

const mockStats = {
  total: 50,
  pending: 2,
  queued: 3,
  running: 3,
  completed: 30,
  failed: 10,
  cancelled: 0,
  completed_24h: 2,
  failed_cancelled_24h: 1,
  running_long_30min: 0,
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setupDefaultMocks() {
  mockApi.getTaskFilterOptions.mockResolvedValue({
    initiators: [
      { value: 'user:1', kind: 'user', user_id: 1, username: 'alice', display_name: 'Alice', count: 12 },
      { value: 'user:2', kind: 'user', user_id: 2, username: 'bob', display_name: null, count: 6 },
      { value: 'user:3', kind: 'user', user_id: 3, username: 'charlie', display_name: null, count: 1 },
    ],
    harnesses: [],
  })
  mockApi.getProjects.mockResolvedValue(mockProjects)
  mockApi.getTasksPaginated.mockResolvedValue({ items: mockTasks, total: mockTasks.length })
  mockApi.getStats.mockResolvedValue(mockStats)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('TaskList', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    mockIsMobileRef.value = false
    router.push('/')
    await router.isReady()

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

  async function mountComponent() {
    setupDefaultMocks()
    wrapper = mount(TaskList, { global: { plugins: [router] } })
    await flushPromises()
    await nextTick()
    return wrapper
  }

  // -----------------------------------------------------------------------
  // 1. Basic rendering
  // -----------------------------------------------------------------------
  describe('basic rendering', () => {
    it('renders the tasks page root element', async () => {
      await mountComponent()
      expect(wrapper.find('[data-testid="tasks-page"]').exists()).toBe(true)
    })

    it('shows page header', async () => {
      await mountComponent()
      expect(wrapper.find('.page-header-mock').exists()).toBe(true)
    })

    it('shows 4 summary cards after loading', async () => {
      await mountComponent()
      const cards = wrapper.findAll('.summary-card-mock')
      expect(cards.length).toBe(4)
    })

    it('renders filter toolbar', async () => {
      await mountComponent()
      expect(wrapper.find('[data-testid="filter-toolbar"]').exists()).toBe(true)
    })

    it('renders data table', async () => {
      await mountComponent()
      expect(wrapper.find('.n-data-table').exists()).toBe(true)
    })

    it('wraps data table in an internal horizontal scroll container', async () => {
      await mountComponent()
      expect(wrapper.find('.dashboard-table-shell').exists()).toBe(true)
      expect(wrapper.findComponent({ name: 'NDataTable' }).props('scrollX')).toBeGreaterThan(0)
    })

    it('renders refresh button in header', async () => {
      await mountComponent()
      const button = wrapper.find('.page-header-mock button.n-button')
      expect(button.exists()).toBe(true)
      expect(button.text()).toBe('common.refresh')
    })
  })

  // -----------------------------------------------------------------------
  // 2. Initial data fetching
  // -----------------------------------------------------------------------
  describe('initial data fetching', () => {
    it('calls getProjects on mount', async () => {
      await mountComponent()
      expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
    })

    it('calls getStats on mount', async () => {
      await mountComponent()
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })

    it('calls getTasksPaginated on mount with correct params', async () => {
      await mountComponent()
      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({
          page: 1,
          page_size: 20,
          sort_by: 'created_at',
          sort_order: 'desc',
        }),
      )
    })

    it('starts polling on mount', async () => {
      await mountComponent()
      expect(mockStartPolling).toHaveBeenCalledTimes(1)
    })

    it('populates tasks from response', async () => {
      await mountComponent()
      expect(wrapper.vm.tasks).toHaveLength(3)
      expect(wrapper.vm.tasks[0].id).toBe(1)
    })

    it('populates totalTasks from response', async () => {
      await mountComponent()
      expect(wrapper.vm.totalTasks).toBe(3)
    })
  })

  // -----------------------------------------------------------------------
  // 3. Summary cards
  // -----------------------------------------------------------------------
  describe('summary cards', () => {
    it('displays correct stat values from getStats', async () => {
      await mountComponent()
      const cards = wrapper.findAll('.summary-card-mock')
      expect(cards.length).toBe(4)

      // statsTotal=50, statsRunning=3, statsPending=2+3=5, statsCompleted=30
      expect(cards[0].text()).toBe('dashboard.visibleTasks: 50')
      expect(cards[1].text()).toBe('dashboard.running: 3')
      expect(cards[2].text()).toBe('dashboard.pendingQueued: 5')
      expect(cards[3].text()).toBe('dashboard.completed: 30')
    })

    it('summary cards are hidden before first load', async () => {
      setupDefaultMocks()
      let resolveTasks!: (v: any) => void
      mockApi.getTasksPaginated.mockReturnValue(new Promise(r => { resolveTasks = r }) as any)

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await nextTick()

      // hasLoadedOnce is false, so n-grid with summary cards should not render
      expect(wrapper.vm.hasLoadedOnce).toBe(false)
      expect(wrapper.findAll('.summary-card-mock').length).toBe(0)

      resolveTasks({ items: [], total: 0 })
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // 4. Data table
  // -----------------------------------------------------------------------
  describe('data table', () => {
    it('renders task rows in the table', async () => {
      await mountComponent()
      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows.length).toBe(3)
      expect(rows[0].attributes('data-id')).toBe('1')
      expect(rows[1].attributes('data-id')).toBe('2')
      expect(rows[2].attributes('data-id')).toBe('3')
    })

    it('renders empty table when no tasks', async () => {
      setupDefaultMocks()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows.length).toBe(0)
    })
  })

  // -----------------------------------------------------------------------
  // 5. Search behavior
  // -----------------------------------------------------------------------
  describe('search behavior', () => {
    it('includes search param when term >= 2 chars', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('test')
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'test' }),
      )
    })

    it('includes search param when term is exactly 2 chars', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('ab')
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'ab' }),
      )
    })

    it('does NOT include search param when term < 2 chars', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('t')
      await flushPromises()

      const callArgs = mockApi.getTasksPaginated.mock.calls[0][0]
      expect(callArgs).not.toHaveProperty('search')
    })

    it('does NOT include search param when term is empty', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('')
      await flushPromises()

      const callArgs = mockApi.getTasksPaginated.mock.calls[0][0]
      expect(callArgs).not.toHaveProperty('search')
    })

    it('resets page to 1 when searching', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('test query')
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1 }),
      )
    })
  })

  // -----------------------------------------------------------------------
  // 6. Row navigation
  // -----------------------------------------------------------------------
  describe('row navigation', () => {
    it('getRowProps returns cursor pointer style', async () => {
      await mountComponent()
      const props = wrapper.vm.getRowProps(mockTasks[0])
      expect(props.style).toBe('cursor: pointer;')
    })

    it('navigates to /tasks/:id on row click (non-interactive target)', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.getRowProps(mockTasks[0])

      const mockEvent = { target: document.createElement('div') } as any as MouseEvent
      props.onClick(mockEvent)

      expect(pushSpy).toHaveBeenCalledWith({ name: 'TaskView', params: { id: 1 } })
    })

    it('does NOT navigate when clicking an interactive target', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.getRowProps(mockTasks[0])

      // Simulate clicking a button inside the row
      const button = document.createElement('button')
      const mockEvent = { target: button } as any as MouseEvent
      props.onClick(mockEvent)

      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('does NOT navigate when clicking an anchor inside the row', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.getRowProps(mockTasks[0])

      const anchor = document.createElement('a')
      const mockEvent = { target: anchor } as any as MouseEvent
      props.onClick(mockEvent)

      expect(pushSpy).not.toHaveBeenCalled()
    })
  })

  // -----------------------------------------------------------------------
  // 7. Loading state
  // -----------------------------------------------------------------------
  describe('loading state', () => {
    it('initialLoading is true before first fetch completes', async () => {
      let resolveTasks!: (v: any) => void
      const pending = new Promise(r => { resolveTasks = r })

      setupDefaultMocks()
      mockApi.getTasksPaginated.mockReturnValue(pending as any)

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(true)
      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.hasLoadedOnce).toBe(false)

      resolveTasks({ items: [], total: 0 })
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(false)
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('initialLoading is false after first load completes', async () => {
      await mountComponent()
      expect(wrapper.vm.initialLoading).toBe(false)
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('tableLoading is true during subsequent fetches', async () => {
      await mountComponent()

      // hasLoadedOnce is now true
      expect(wrapper.vm.hasLoadedOnce).toBe(true)

      let resolveTasks!: (v: any) => void
      mockApi.getTasksPaginated.mockReturnValue(new Promise(r => { resolveTasks = r }) as any)

      // Trigger a new fetch via search
      wrapper.vm.onSearch('test query')
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.tableLoading).toBe(true)
      // initialLoading should be false because hasLoadedOnce is true
      expect(wrapper.vm.initialLoading).toBe(false)

      resolveTasks({ items: [], total: 0 })
      await flushPromises()
    })

    it('shows spinner when initialLoading is true', async () => {
      let resolveTasks!: (v: any) => void
      const pending = new Promise(r => { resolveTasks = r })

      setupDefaultMocks()
      mockApi.getTasksPaginated.mockReturnValue(pending as any)

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.find('.n-spin-loading').exists()).toBe(true)

      resolveTasks({ items: [], total: 0 })
      await flushPromises()
      await nextTick()

      expect(wrapper.find('.n-spin-loading').exists()).toBe(false)
      expect(wrapper.find('.n-spin').exists()).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // 8. Error handling
  // -----------------------------------------------------------------------
  describe('error handling', () => {
    it('shows error message when getTasksPaginated fails', async () => {
      setupDefaultMocks()
      mockApi.getTasksPaginated.mockRejectedValue(new Error('Network error'))

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      expect(mockMessage.error).toHaveBeenCalledWith('dashboard.failedToFetchTasks')
    })

    it('sets hasLoadedOnce even when fetch fails', async () => {
      setupDefaultMocks()
      mockApi.getTasksPaginated.mockRejectedValue(new Error('Network error'))

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('handles getStats failure silently', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockRejectedValue(new Error('Stats down'))

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await flushPromises()

      // No error message for stats failure (main fetch succeeds)
      expect(mockMessage.error).not.toHaveBeenCalled()
      // Stats remain at default values (0)
      expect(wrapper.vm.statsTotal).toBe(0)
      expect(wrapper.vm.statsRunning).toBe(0)
      expect(wrapper.vm.statsCompleted).toBe(0)
    })

    it('exposes project option loading failure and supports retry', async () => {
      setupDefaultMocks()
      mockApi.getProjects.mockRejectedValue(new Error('Projects down'))

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await flushPromises()

      expect(mockMessage.error).not.toHaveBeenCalled()
      expect(wrapper.vm.tasks).toHaveLength(3)
      expect(wrapper.vm.projectOptionsError).toBe(true)

      mockApi.getProjects.mockResolvedValue(mockProjects)
      const projectField = wrapper.vm.filterConfig.filterFields.find(
        (field: any) => field.key === 'project_id',
      )
      await projectField.optionsRetry()
      expect(wrapper.vm.projectOptionsError).toBe(false)
      expect(projectField.options()).toHaveLength(2)
    })
  })

  // -----------------------------------------------------------------------
  // 9. fetchTasks concurrency
  // -----------------------------------------------------------------------
  describe('fetchTasks concurrency', () => {
    it('keeps the latest response when requests overlap', async () => {
      setupDefaultMocks()
      let resolveFirst!: (v: any) => void
      let resolveSecond!: (v: any) => void
      mockApi.getTasksPaginated
        .mockReturnValueOnce(new Promise(r => { resolveFirst = r }) as any)
        .mockReturnValueOnce(new Promise(r => { resolveSecond = r }) as any)

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      wrapper.vm.$.setupState.fetchTasks()
      await nextTick()
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(2)

      const latestTask = createMockTask({ id: 99, user_prompt: 'Latest' })
      resolveSecond({ items: [latestTask], total: 1 })
      await flushPromises()
      expect(wrapper.vm.tasks[0].id).toBe(99)

      resolveFirst({ items: mockTasks, total: mockTasks.length })
      await flushPromises()
      expect(wrapper.vm.tasks[0].id).toBe(99)
    })

    it('skips a background poll while the current request is still loading', async () => {
      setupDefaultMocks()
      let resolveTasks!: (v: any) => void
      mockApi.getTasksPaginated.mockReturnValue(
        new Promise(r => { resolveTasks = r }) as any,
      )

      wrapper = mount(TaskList, { global: { plugins: [router] } })
      await nextTick()
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)

      await wrapper.vm.$.setupState.fetchTasks({ skipIfLoading: true })
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)

      resolveTasks({ items: mockTasks, total: mockTasks.length })
      await flushPromises()
    })
  })

  // -----------------------------------------------------------------------
  // 10. Initiator filter options
  // -----------------------------------------------------------------------
  describe('initiator filter options', () => {
    it('loads complete initiator options independently from the current page', async () => {
      await mountComponent()
      expect(mockApi.getTaskFilterOptions).toHaveBeenCalledTimes(1)
      expect(wrapper.vm.initiatorFilterOptions).toHaveLength(3)
      expect(wrapper.vm.initiatorFilterOptions[2].username).toBe('charlie')
    })
  })

  // -----------------------------------------------------------------------
  // 11. Column render functions
  // -----------------------------------------------------------------------
  describe('column render functions', () => {
    const fullTask = createMockTask({
      id: 10,
      status: 'running',
      user_prompt: 'Implement feature X',
      project_name: 'my-project',
      project_url: 'https://gitlab.example.com/group/my-project',
      project_id: 5,
      initiator_username: 'alice',
      priority: 0,
      additions: 42,
      deletions: 13,
      input_tokens: 1500,
      output_tokens: 800,
      created_at: '2026-04-01T12:00:00Z',
      scheduled_at: '2026-04-01T13:00:00Z',
      issue: {
        id: 7,
        title: 'Feature X',
        branch_name: 'codify/issue-7',
        base_branch: 'main',
        target_branch: 'main',
        merge_request_iid: 42,
        merge_request_url: 'https://gitlab.example.com/group/my-project/-/merge_requests/42',
      },
    })

    const minimalTask = createMockTask({
      id: 11,
      status: 'pending',
      user_prompt: '',
      project_name: null,
      project_url: null,
      project_id: 99,
      initiator_username: null,
      priority: 2,
      additions: 0,
      deletions: 0,
      input_tokens: null,
      output_tokens: null,
      created_at: '2026-04-01T12:00:00Z',
      scheduled_at: null,
      issue: undefined,
    })

    function getColumn(columns: any[], key: string) {
      return columns.find((c: any) => c.key === key)
    }

    it('renders status column with correct tag type for running', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'status')
      const result = col.render(fullTask, 0)
      expect(result).toBeDefined()
      expect(result.props?.type).toBe('warning')
    })

    it('renders status column for completed task', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'status')
      const result = col.render({ ...fullTask, status: 'completed' }, 0)
      expect(result.props?.type).toBe('success')
    })

    it('renders status column for failed task', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'status')
      const result = col.render({ ...fullTask, status: 'failed' }, 0)
      expect(result.props?.type).toBe('error')
    })


    it('renders project column with external link', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'project')
      const result = col.render(fullTask, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(2)
    })

    it('renders project column without link when no project_url', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'project')
      const result = col.render(minimalTask, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(2)
    })

    it('renders initiator column with username', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'initiator_username')
      expect(col.render(fullTask, 0)).toBe('alice')
    })

    it('renders initiator column with dash when no username', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'initiator_username')
      expect(col.render(minimalTask, 0)).toBe('-')
    })

    it('renders prompt column with compact width and wrapping hover tooltip', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'user_prompt')
      expect(col).toBeDefined()
      expect(col.title).toBe('dashboard.prompt')
      expect(col.width).toBeLessThanOrEqual(220)
      expect(col.ellipsis.tooltip.style).toMatchObject({
        maxWidth: '420px',
        whiteSpace: 'pre-wrap',
        wordBreak: 'break-word',
      })
      expect(col.render(fullTask, 0)).toBe('Implement feature X')
    })

    it('renders prompt column with dash when prompt is empty', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'user_prompt')
      expect(col.render(minimalTask, 0)).toBe('-')
    })

    it('renders issue column with link when issue exists', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'issue')
      const result = col.render(fullTask, 0)
      expect(result.type).toBe('a')
      expect(result.children).toBe('#7 Feature X')
    })

    it('renders issue column with dash when no issue', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'issue')
      expect(col.render(minimalTask, 0)).toBe('-')
    })

    it('issue column click navigates to issue page', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'issue')
      const result = col.render(fullTask, 0)
      const mockEvent = { stopPropagation: vi.fn() }
      result.props.onClick(mockEvent)
      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(pushSpy).toHaveBeenCalledWith('/issues/7')
    })

    it('renders priority column', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'priority')
      expect(col.render(fullTask, 0)).toBe('P0')
    })

    it('renders branch column with branch name', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'branch_name')
      expect(col.render(fullTask, 0)).toBe('codify/issue-7')
    })

    it('renders branch column with dash when no branch', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'branch_name')
      expect(col.render(minimalTask, 0)).toBe('-')
    })

    it('renders MR column with link when MR exists', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'merge_request_url')
      const result = col.render(fullTask, 0)
      expect(result.type).toBe('a')
      expect(result.props?.href).toBe('https://gitlab.example.com/group/my-project/-/merge_requests/42')
      expect(result.children).toBe('!42')
    })

    it('renders MR column with "MR" label when no iid', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'merge_request_url')
      const taskNoIid = createMockTask({
        issue: {
          id: 5,
          title: 'Test',
          branch_name: 'test',
          base_branch: 'main',
          target_branch: 'main',
          merge_request_iid: null,
          merge_request_url: 'https://gitlab.example.com/mr',
        },
      })
      const result = col.render(taskNoIid, 0)
      expect(result.type).toBe('a')
      expect(result.children).toBe('MR')
    })

    it('renders MR column with dash when no MR', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'merge_request_url')
      expect(col.render(minimalTask, 0)).toBe('-')
    })

    it('renders changes column with breakdown', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'changes')
      const result = col.render(fullTask, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(2)
    })

    it('renders changes column with dash when no changes', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'changes')
      expect(col.render(minimalTask, 0)).toBe('—')
    })

    it('renders tokens column with breakdown', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'tokens')
      const result = col.render(fullTask, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(3)
    })

    it('renders tokens column with dash when no tokens', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'tokens')
      expect(col.render(minimalTask, 0)).toBe('—')
    })

    it('renders created_at column with formatted date', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'created_at')
      expect(col.render(fullTask, 0)).toBe('formatted-2026-04-01T12:00:00Z')
    })

    it('renders scheduled_at column with formatted date', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'scheduled_at')
      expect(col.render(fullTask, 0)).toBe('formatted-2026-04-01T13:00:00Z')
    })

    it('renders scheduled_at column with dash when null', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).allDesktopColumns
      const col = getColumn(cols, 'scheduled_at')
      expect(col.render(minimalTask, 0)).toBe('-')
    })
  })

  // -----------------------------------------------------------------------
  // 12. Mobile columns
  // -----------------------------------------------------------------------
  describe('mobile columns', () => {
    beforeEach(() => {
      mockIsMobileRef.value = true
    })

    it('returns 3 mobile columns when isMobile is true', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).columns
      expect(cols).toHaveLength(3)
      expect(cols.map((c: any) => c.key)).toEqual(['id', 'task_info', 'status'])
    })

    it('mobile task_info renders project label and branch link', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).columns
      const taskInfoCol = cols.find((c: any) => c.key === 'task_info')
      const task = createMockTask({
        project_name: 'my-proj',
        issue: {
          id: 3,
          title: 'Test issue',
          branch_name: 'codify/issue-3',
          base_branch: 'main',
          target_branch: 'main',
          merge_request_iid: null,
          merge_request_url: null,
        },
      })
      const result = taskInfoCol.render(task, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(2)
    })

    it('mobile task_info renders dash for branch when no branch', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).columns
      const taskInfoCol = cols.find((c: any) => c.key === 'task_info')
      const task = createMockTask({
        issue: {
          id: 3,
          title: 'Test',
          branch_name: null,
          base_branch: 'main',
          target_branch: 'main',
          merge_request_iid: null,
          merge_request_url: null,
        },
      })
      const result = taskInfoCol.render(task, 0)
      expect(result.children[1].children).toBe('-')
    })

    it('mobile task_info without issue shows dash in secondary label', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).columns
      const taskInfoCol = cols.find((c: any) => c.key === 'task_info')
      const task = createMockTask({ issue: undefined })
      const result = taskInfoCol.render(task, 0)
      expect(result.type).toBe('div')
      expect(result.children).toHaveLength(2)
      expect(result.children[1].children).toBe('-')
    })

    it('mobile status column renders NTag with correct type', async () => {
      await mountComponent()
      const cols = (wrapper.vm as any).columns
      const statusCol = cols.find((c: any) => c.key === 'status')
      const task = createMockTask({ status: 'failed' })
      const result = statusCol.render(task, 0)
      expect(result).toBeDefined()
      expect(result.props?.type).toBe('error')
    })
  })

  // -----------------------------------------------------------------------
  // 13. Filter config options
  // -----------------------------------------------------------------------
  describe('filter config options', () => {
    it('status options returns 6 statuses', async () => {
      await mountComponent()
      const config = (wrapper.vm as any).filterConfig
      const field = config.filterFields.find((f: any) => f.key === 'status')
      const options = field.options()
      expect(options).toHaveLength(6)
      expect(options.map((o: any) => o.value)).toEqual([
        'pending', 'queued', 'running', 'completed', 'failed', 'cancelled'
      ])
    })

    it('project options returns loaded projects', async () => {
      await mountComponent()
      const config = (wrapper.vm as any).filterConfig
      const field = config.filterFields.find((f: any) => f.key === 'project_id')
      const options = field.options()
      expect(options).toHaveLength(2)
      expect(options[0]).toEqual({ label: 'group/project-1', value: 1 })
      expect(options[1]).toEqual({ label: 'group/project-2', value: 2 })
    })

    it('priority options returns 3 levels', async () => {
      await mountComponent()
      const config = (wrapper.vm as any).filterConfig
      const field = config.filterFields.find((f: any) => f.key === 'priority')
      const options = field.options()
      expect(options).toHaveLength(3)
      expect(options.map((o: any) => o.value)).toEqual(['0', '1', '2'])
    })

    it('initiator options use stable user values and counts', async () => {
      await mountComponent()
      const config = (wrapper.vm as any).filterConfig
      const field = config.filterFields.find((f: any) => f.key === 'initiator')
      const options = field.options()
      expect(options).toHaveLength(3)
      expect(options[0]).toEqual({ label: 'Alice (@alice)', value: 'user:1', count: 12 })
      expect(options[2]).toEqual({ label: 'charlie', value: 'user:3', count: 1 })
    })

    it('has_mr options returns true/false', async () => {
      await mountComponent()
      const config = (wrapper.vm as any).filterConfig
      const field = config.filterFields.find((f: any) => f.key === 'has_mr')
      const options = field.options()
      expect(options).toHaveLength(2)
      expect(options.map((o: any) => o.value)).toEqual(['true', 'false'])
    })

    it('rejects invalid URL values for status, project, priority, and MR filters', async () => {
      await mountComponent()
      const fields = (wrapper.vm as any).filterConfig.filterFields

      expect(fields.find((field: any) => field.key === 'status').parseValue('bogus')).toBeUndefined()
      expect(fields.find((field: any) => field.key === 'project_id').parseValue('-1')).toBeUndefined()
      expect(fields.find((field: any) => field.key === 'priority').parseValue('3')).toBeUndefined()
      expect(fields.find((field: any) => field.key === 'has_mr').parseValue('yes')).toBeUndefined()
    })
  })

  // -----------------------------------------------------------------------
  // 14. Pagination callbacks
  // -----------------------------------------------------------------------
  describe('pagination callbacks', () => {
    it('onUpdate:page changes page and fetches', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      const pag = (wrapper.vm as any).pagination
      pag['onUpdate:page'](3)
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({ page: 3 }),
      )
    })

    it('onUpdate:pageSize changes size, resets page, and fetches', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })

      const pag = (wrapper.vm as any).pagination
      pag['onUpdate:pageSize'](50)
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, page_size: 50 }),
      )
    })
  })

  // -----------------------------------------------------------------------
  // 15. refreshTasks
  // -----------------------------------------------------------------------
  describe('refreshTasks', () => {
    it('calls fetchTasks and fetchStats', async () => {
      await mountComponent()
      mockApi.getTasksPaginated.mockClear()
      mockApi.getStats.mockClear()
      mockApi.getTasksPaginated.mockResolvedValue({ items: [], total: 0 })
      mockApi.getStats.mockResolvedValue(mockStats)

      ;(wrapper.vm as any).refreshTasks()
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })
  })
})
