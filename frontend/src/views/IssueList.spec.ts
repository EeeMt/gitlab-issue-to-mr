import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import IssueList from './IssueList.vue'
import { createMockProject } from '../test/mocks/api'
import type { Issue } from '../api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getIssueFilterOptions: vi.fn<() => Promise<any>>(),
    getProjects: vi.fn<() => Promise<any>>(),
    getIssues: vi.fn<() => Promise<any>>(),
    getStats: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

const mockFilterState = vi.hoisted(() => ({
  filters: { value: {} },
  sort: { value: { field: 'created_at', order: 'desc' as const } },
  visibleColumns: { value: ['id', 'title', 'project_id', 'status', 'task_count', 'merge_request', 'total_changes', 'duration', 'total_tokens', 'created_at'] },
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

vi.mock('../api', () => ({
  getIssueFilterOptions: mockApi.getIssueFilterOptions,
  getProjects: mockApi.getProjects,
  getIssues: mockApi.getIssues,
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
    props: ['columns', 'data', 'loading', 'row-key', 'row-props', 'bordered', 'pagination', 'remote'],
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

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({ isMobile: ref(false), isCompact: ref(false), width: ref(1200) }),
}))

// ---------------------------------------------------------------------------
// Icon stubs
// ---------------------------------------------------------------------------
vi.mock('@vicons/ionicons5', () => ({
  EllipseOutline: {},
  FolderOpenOutline: {},
  PersonOutline: {},
  CalendarOutline: {},
  GitMergeOutline: {},
  DocumentTextOutline: {},
  AlertCircleOutline: {},
  SyncOutline: {},
  CheckmarkCircleOutline: {},
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
function createMockIssue(overrides: Record<string, any> = {}): Issue {
  return {
    id: 1,
    title: 'Test Issue',
    description: 'Test desc',
    project_id: 1,
    status: 'open',
    branch_name: 'codify/issue-1',
    base_branch: 'main',
    target_branch: 'main',
	    merge_request_iid: null,
	    merge_request_url: null,
	    ci_auto_repair_enabled: false,
	    claude_session_id: null,
    initiator_user_id: 1,
    initiator_username: 'testuser',
    created_at: '2024-01-01T10:00:00Z',
    updated_at: '2024-01-01T10:00:00Z',
    task_count: 3,
    totals: {
      additions: 10,
      deletions: 5,
      total_changes: 15,
      input_tokens: 1000,
      output_tokens: 500,
      duration_seconds: 5400,
    },
    ...overrides,
  } as Issue
}

const mockProjects = [
  createMockProject({ id: 1, name: 'project-1', path_with_namespace: 'group/project-1' }),
  createMockProject({ id: 2, name: 'project-2', path_with_namespace: 'group/project-2' }),
]

const mockIssues = [
  createMockIssue({ id: 1, title: 'Bug: login broken', status: 'open', project_id: 1, initiator_username: 'alice' }),
  createMockIssue({ id: 2, title: 'Feature: dark mode', status: 'in_progress', project_id: 1, initiator_username: 'bob' }),
  createMockIssue({ id: 3, title: 'Refactor: cleanup', status: 'closed', project_id: 2, initiator_username: 'alice' }),
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
  issues: {
    total: 15,
    by_status: {
      open: 5,
      in_progress: 3,
      in_review: 6,
      closed: 1,
    },
  },
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setupDefaultMocks() {
  mockApi.getIssueFilterOptions.mockResolvedValue({
    initiators: [
      { value: 'user:1', kind: 'user', user_id: 1, username: 'alice', display_name: 'Alice', count: 10 },
      { value: 'user:2', kind: 'user', user_id: 2, username: 'bob', display_name: null, count: 8 },
      { value: 'user:3', kind: 'user', user_id: 3, username: 'charlie', display_name: null, count: 2 },
    ],
  })
  mockApi.getProjects.mockResolvedValue(mockProjects)
  mockApi.getIssues.mockResolvedValue({ items: mockIssues, total: mockIssues.length })
  mockApi.getStats.mockResolvedValue(mockStats)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('IssueList', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
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
    wrapper = mount(IssueList, { global: { plugins: [router] } })
    await flushPromises()
    await nextTick()
    return wrapper
  }

  // -----------------------------------------------------------------------
  // 1. Basic rendering
  // -----------------------------------------------------------------------
  describe('basic rendering', () => {
    it('renders the issue list page root element', async () => {
      await mountComponent()
      expect(wrapper.find('[data-testid="issue-list-page"]').exists()).toBe(true)
    })

    it('shows page header', async () => {
      await mountComponent()
      expect(wrapper.find('.page-header-mock').exists()).toBe(true)
    })

    it('shows create button in header', async () => {
      await mountComponent()
      const button = wrapper.find('.page-header-mock button.n-button')
      expect(button.exists()).toBe(true)
      expect(button.text()).toBe('issue.create')
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
  })

  // -----------------------------------------------------------------------
  // 2. Initial data fetching
  // -----------------------------------------------------------------------
  describe('initial data fetching', () => {
    it('calls getProjects on mount', async () => {
      await mountComponent()
      expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
    })

    it('calls getIssues on mount with correct params', async () => {
      await mountComponent()
      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({
          page: 1,
          page_size: 20,
          sort_by: 'created_at',
          sort_order: 'desc',
        }),
      )
    })

    it('calls getStats on mount', async () => {
      await mountComponent()
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })

    it('populates issues from response', async () => {
      await mountComponent()
      expect(wrapper.vm.issues).toHaveLength(3)
      expect(wrapper.vm.issues[0].id).toBe(1)
    })

    it('populates totalIssues from response', async () => {
      await mountComponent()
      expect(wrapper.vm.totalIssues).toBe(3)
    })
  })

  // -----------------------------------------------------------------------
  // 3. Summary cards
  // -----------------------------------------------------------------------
  describe('summary cards', () => {
    it('displays correct issue stat values from getStats', async () => {
      await mountComponent()
      const cards = wrapper.findAll('.summary-card-mock')
      expect(cards.length).toBe(4)

      // From stats.issues: total=15, open=5, in_progress=3, in_review=6 (mapped to completed)
      expect(cards[0].text()).toBe('issue.totalIssues: 15')
      expect(cards[1].text()).toBe('issue.openCount: 5')
      expect(cards[2].text()).toBe('issue.inProgressCount: 3')
      expect(cards[3].text()).toBe('issue.completedCount: 6')
    })

    it('shows zero stats when getStats returns no issues section', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockResolvedValue({
        ...mockStats,
        issues: undefined,
      })

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      // Stats should remain at default (0)
      expect(wrapper.vm.statsTotal).toBe(0)
      expect(wrapper.vm.statsOpen).toBe(0)
      expect(wrapper.vm.statsInProgress).toBe(0)
      expect(wrapper.vm.statsCompleted).toBe(0)
    })

    it('summary cards are hidden before first load', async () => {
      setupDefaultMocks()
      let resolveIssues!: (v: any) => void
      mockApi.getIssues.mockReturnValue(new Promise(r => { resolveIssues = r }) as any)

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.hasLoadedOnce).toBe(false)
      expect(wrapper.findAll('.summary-card-mock').length).toBe(0)

      resolveIssues({ items: [], total: 0 })
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // 4. Data table
  // -----------------------------------------------------------------------
  describe('data table', () => {
    it('renders issue rows in the table', async () => {
      await mountComponent()
      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows.length).toBe(3)
      expect(rows[0].attributes('data-id')).toBe('1')
      expect(rows[1].attributes('data-id')).toBe('2')
      expect(rows[2].attributes('data-id')).toBe('3')
    })

    it('renders empty table when no issues', async () => {
      setupDefaultMocks()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows.length).toBe(0)
    })

    it('adds duration to the sort menu and default visible columns', async () => {
      await mountComponent()

      expect(wrapper.vm.filterConfig.sortFields).toContainEqual({
        key: 'duration',
        label: 'filter.sortDuration',
      })
      expect(wrapper.vm.filterConfig.columns).toContainEqual({
        key: 'duration',
        label: 'dashboard.duration',
        defaultVisible: true,
      })
      expect(wrapper.vm.columns.some((column: any) => column.key === 'duration')).toBe(true)
    })

    it('renders issue total task duration from totals', async () => {
      await mountComponent()
      const durationColumn = wrapper.vm.allColumns.find((column: any) => column.key === 'duration')

      expect(durationColumn.render(createMockIssue({
        totals: {
          additions: 0,
          deletions: 0,
          total_changes: 0,
          input_tokens: 0,
          output_tokens: 0,
          duration_seconds: 3661,
        },
      }))).toBe('1h 1m')
    })
  })

  // -----------------------------------------------------------------------
  // 5. Create button navigation
  // -----------------------------------------------------------------------
  describe('create button navigation', () => {
    it('navigates to /issues/create when create button is clicked', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')

      const button = wrapper.find('.page-header-mock button.n-button')
      await button.trigger('click')

      expect(pushSpy).toHaveBeenCalledWith('/issues/create')
    })
  })

  // -----------------------------------------------------------------------
  // 6. Row navigation
  // -----------------------------------------------------------------------
  describe('row navigation', () => {
    it('issueRowProps returns cursor pointer style', async () => {
      await mountComponent()
      const props = wrapper.vm.issueRowProps(mockIssues[0])
      expect(props.style).toBe('cursor: pointer')
    })

    it('navigates to /issues/:id on row click', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.issueRowProps(mockIssues[0])

      props.onClick()

      expect(pushSpy).toHaveBeenCalledWith('/issues/1')
    })

    it('navigates to correct issue for different rows', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const props = wrapper.vm.issueRowProps(mockIssues[1])

      props.onClick()

      expect(pushSpy).toHaveBeenCalledWith('/issues/2')
    })
  })

  // -----------------------------------------------------------------------
  // 7. Search behavior
  // -----------------------------------------------------------------------
  describe('search behavior', () => {
    it('includes search param when term >= 2 chars', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('test')
      await flushPromises()

      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'test' }),
      )
    })

    it('includes search param when term is exactly 2 chars', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('ab')
      await flushPromises()

      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({ search: 'ab' }),
      )
    })

    it('does NOT include search param when term < 2 chars', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('t')
      await flushPromises()

      const callArgs = mockApi.getIssues.mock.calls[0][0]
      expect(callArgs).not.toHaveProperty('search')
    })

    it('does NOT include search param when term is empty', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('')
      await flushPromises()

      const callArgs = mockApi.getIssues.mock.calls[0][0]
      expect(callArgs).not.toHaveProperty('search')
    })

    it('resets page to 1 when searching', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      wrapper.vm.onSearch('test query')
      await flushPromises()

      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1 }),
      )
    })
  })

  // -----------------------------------------------------------------------
  // 8. Loading state
  // -----------------------------------------------------------------------
  describe('loading state', () => {
    it('initialLoading is true before first fetch completes', async () => {
      let resolveIssues!: (v: any) => void
      const pending = new Promise(r => { resolveIssues = r })

      setupDefaultMocks()
      mockApi.getIssues.mockReturnValue(pending as any)

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(true)
      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.hasLoadedOnce).toBe(false)

      resolveIssues({ items: [], total: 0 })
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

      expect(wrapper.vm.hasLoadedOnce).toBe(true)

      let resolveIssues!: (v: any) => void
      mockApi.getIssues.mockReturnValue(new Promise(r => { resolveIssues = r }) as any)

      wrapper.vm.onSearch('test query')
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.tableLoading).toBe(true)
      expect(wrapper.vm.initialLoading).toBe(false)

      resolveIssues({ items: [], total: 0 })
      await flushPromises()
    })

    it('shows spinner when initialLoading is true', async () => {
      let resolveIssues!: (v: any) => void
      const pending = new Promise(r => { resolveIssues = r })

      setupDefaultMocks()
      mockApi.getIssues.mockReturnValue(pending as any)

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.find('.n-spin-loading').exists()).toBe(true)

      resolveIssues({ items: [], total: 0 })
      await flushPromises()
      await nextTick()

      expect(wrapper.find('.n-spin-loading').exists()).toBe(false)
      expect(wrapper.find('.n-spin').exists()).toBe(true)
    })
  })

  // -----------------------------------------------------------------------
  // 9. Error handling
  // -----------------------------------------------------------------------
  describe('error handling', () => {
    it('shows error message when getIssues fails', async () => {
      setupDefaultMocks()
      mockApi.getIssues.mockRejectedValue(new Error('Network error'))

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()
      await nextTick()

      expect(mockMessage.error).toHaveBeenCalledWith('issue.loadFailed')
    })

    it('sets hasLoadedOnce even when fetch fails', async () => {
      setupDefaultMocks()
      mockApi.getIssues.mockRejectedValue(new Error('Network error'))

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()

      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('handles getStats failure silently', async () => {
      setupDefaultMocks()
      mockApi.getStats.mockRejectedValue(new Error('Stats down'))

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()

      expect(mockMessage.error).not.toHaveBeenCalled()
      expect(wrapper.vm.statsTotal).toBe(0)
      expect(wrapper.vm.statsOpen).toBe(0)
      expect(wrapper.vm.statsInProgress).toBe(0)
      expect(wrapper.vm.statsCompleted).toBe(0)
    })

    it('exposes project option loading failure and supports retry', async () => {
      setupDefaultMocks()
      mockApi.getProjects.mockRejectedValue(new Error('Projects down'))

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await flushPromises()

      expect(mockMessage.error).not.toHaveBeenCalled()
      expect(wrapper.vm.issues).toHaveLength(3)
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
  // 10. fetchIssues concurrency
  // -----------------------------------------------------------------------
  describe('fetchIssues concurrency', () => {
    it('keeps the latest response when requests overlap', async () => {
      setupDefaultMocks()
      let resolveFirst!: (v: any) => void
      let resolveSecond!: (v: any) => void
      mockApi.getIssues
        .mockReturnValueOnce(new Promise(r => { resolveFirst = r }) as any)
        .mockReturnValueOnce(new Promise(r => { resolveSecond = r }) as any)

      wrapper = mount(IssueList, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      wrapper.vm.$.setupState.fetchIssues()
      await nextTick()
      expect(mockApi.getIssues).toHaveBeenCalledTimes(2)

      const latestIssue = createMockIssue({ id: 99, title: 'Latest' })
      resolveSecond({ items: [latestIssue], total: 1 })
      await flushPromises()
      expect(wrapper.vm.issues[0].id).toBe(99)

      resolveFirst({ items: mockIssues, total: mockIssues.length })
      await flushPromises()
      expect(wrapper.vm.issues[0].id).toBe(99)
    })
  })

  // -----------------------------------------------------------------------
  // 11. Creator filter options
  // -----------------------------------------------------------------------
  describe('creator filter options', () => {
    it('loads complete creator options independently from the current page', async () => {
      await mountComponent()
      expect(mockApi.getIssueFilterOptions).toHaveBeenCalledTimes(1)
      expect(wrapper.vm.initiatorFilterOptions).toHaveLength(3)
      expect(wrapper.vm.initiatorFilterOptions[2].username).toBe('charlie')
    })
  })

  // -----------------------------------------------------------------------
  // 12. Column render functions
  // -----------------------------------------------------------------------
  describe('column render functions', () => {
    function getColumn(key: string) {
      return (wrapper.vm.allColumns as any[]).find((c: any) => c.key === key)
    }

    it('renders status column with default type for open', async () => {
      await mountComponent()
      const col = getColumn('status')
      const vnode = col.render(mockIssues[0])
      expect(vnode).toBeDefined()
      expect(vnode.props.type).toBe('default')
    })

    it('renders status column with warning type for in_progress', async () => {
      await mountComponent()
      const col = getColumn('status')
      const vnode = col.render(mockIssues[1])
      expect(vnode.props.type).toBe('warning')
    })

    it('renders status column with success type for closed', async () => {
      await mountComponent()
      const col = getColumn('status')
      const vnode = col.render(mockIssues[2])
      expect(vnode.props.type).toBe('success')
    })

    it('renders project column with project name', async () => {
      await mountComponent()
      const col = getColumn('project_id')
      const result = col.render(mockIssues[0])
      expect(result).toBe('group/project-1')
    })

    it('renders project column fallback for unknown project', async () => {
      await mountComponent()
      const col = getColumn('project_id')
      const result = col.render(createMockIssue({ project_id: 999 }))
      expect(result).toBe('Project #999')
    })

    it('renders task_count column with value', async () => {
      await mountComponent()
      const col = getColumn('task_count')
      const result = col.render(createMockIssue({ task_count: 5 }))
      expect(result).toBe('5')
    })

    it('renders task_count column with 0 when null', async () => {
      await mountComponent()
      const col = getColumn('task_count')
      const result = col.render(createMockIssue({ task_count: null }))
      expect(result).toBe('0')
    })

    it('renders creator column with username', async () => {
      await mountComponent()
      const col = getColumn('initiator_username')
      const result = col.render(mockIssues[0])
      expect(result).toBe('alice')
    })

    it('renders creator column with dash when empty', async () => {
      await mountComponent()
      const col = getColumn('initiator_username')
      const result = col.render(createMockIssue({ initiator_username: '' }))
      expect(result).toBe('-')
    })

    it('renders creator column with dash when null', async () => {
      await mountComponent()
      const col = getColumn('initiator_username')
      const result = col.render(createMockIssue({ initiator_username: null }))
      expect(result).toBe('-')
    })

    it('renders created_at column with formatted date', async () => {
      await mountComponent()
      const col = getColumn('created_at')
      const result = col.render(mockIssues[0])
      expect(result).toBe('formatted-2024-01-01T10:00:00Z')
    })

    it('renders created_at column with dash for null', async () => {
      await mountComponent()
      const col = getColumn('created_at')
      const result = col.render(createMockIssue({ created_at: null }))
      expect(result).toBe('-')
    })

    it('renders title column as vnode', async () => {
      await mountComponent()
      const col = getColumn('title')
      const vnode = col.render(mockIssues[0])
      expect(vnode).toBeDefined()
      expect(vnode.props).toHaveProperty('text', true)
      expect(vnode.props).toHaveProperty('type', 'primary')
    })

    it('title column onClick navigates and stops propagation', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')
      const col = getColumn('title')
      const vnode = col.render(mockIssues[0])
      const mockEvent = { stopPropagation: vi.fn() } as unknown as MouseEvent
      vnode.props.onClick(mockEvent)
      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(pushSpy).toHaveBeenCalledWith('/issues/1')
    })

    it('renders merge_request column with dash when no MR', async () => {
      await mountComponent()
      const col = getColumn('merge_request')
      const result = col.render(createMockIssue({ merge_request_iid: null }))
      expect(result).toBe('—')
    })

    it('renders merge_request column with link when MR has URL', async () => {
      await mountComponent()
      const col = getColumn('merge_request')
      const vnode = col.render(createMockIssue({ merge_request_iid: 42, merge_request_url: 'https://gitlab.com/mr/42' }))
      expect(vnode.props.href).toBe('https://gitlab.com/mr/42')
      expect(vnode.props.target).toBe('_blank')
    })

    it('renders merge_request column with label when MR has no URL', async () => {
      await mountComponent()
      const col = getColumn('merge_request')
      const result = col.render(createMockIssue({ merge_request_iid: 42, merge_request_url: null }))
      expect(result).toBe('!42')
    })

    it('renders total_changes column with dash when no totals', async () => {
      await mountComponent()
      const col = getColumn('total_changes')
      const result = col.render(createMockIssue({ totals: null }))
      expect(result).toBe('—')
    })

    it('renders total_changes column with dash when total_changes is 0', async () => {
      await mountComponent()
      const col = getColumn('total_changes')
      const result = col.render(createMockIssue({
        totals: { additions: 0, deletions: 0, total_changes: 0, input_tokens: 0, output_tokens: 0, duration_seconds: 0 },
      }))
      expect(result).toBe('—')
    })

    it('renders total_changes column with values when present', async () => {
      await mountComponent()
      const col = getColumn('total_changes')
      const vnode = col.render(mockIssues[0])
      expect(vnode).toBeDefined()
      expect(vnode.children).toHaveLength(2)
    })

    it('renders total_tokens column with dash when no totals', async () => {
      await mountComponent()
      const col = getColumn('total_tokens')
      const result = col.render(createMockIssue({ totals: null }))
      expect(result).toBe('—')
    })

    it('renders total_tokens column with dash when all tokens are 0', async () => {
      await mountComponent()
      const col = getColumn('total_tokens')
      const result = col.render(createMockIssue({
        totals: { additions: 0, deletions: 0, total_changes: 0, input_tokens: 0, output_tokens: 0, duration_seconds: 0 },
      }))
      expect(result).toBe('—')
    })

    it('renders total_tokens column with values when present', async () => {
      await mountComponent()
      const col = getColumn('total_tokens')
      const vnode = col.render(mockIssues[0])
      expect(vnode).toBeDefined()
      expect(vnode.children).toHaveLength(3)
    })
  })

  // -----------------------------------------------------------------------
  // 13. Filter config options
  // -----------------------------------------------------------------------
  describe('filter config options', () => {
    it('status filter returns 4 options with correct values', async () => {
      await mountComponent()
      const statusField = (wrapper.vm as any).filterConfig.filterFields.find((f: any) => f.key === 'status')
      const options = statusField.options()
      expect(options).toHaveLength(4)
      expect(options.map((o: any) => o.value)).toEqual(['open', 'in_progress', 'in_review', 'closed'])
    })

    it('project filter maps loaded projects', async () => {
      await mountComponent()
      const projectField = (wrapper.vm as any).filterConfig.filterFields.find((f: any) => f.key === 'project_id')
      const options = projectField.options()
      expect(options).toHaveLength(2)
      expect(options[0]).toEqual({ label: 'group/project-1', value: 1 })
      expect(options[1]).toEqual({ label: 'group/project-2', value: 2 })
    })

    it('creator filter maps scoped options with stable user values and counts', async () => {
      await mountComponent()
      const creatorField = (wrapper.vm as any).filterConfig.filterFields.find((f: any) => f.key === 'initiator')
      const options = creatorField.options()
      expect(options).toHaveLength(3)
      expect(options[0]).toEqual({ label: 'Alice (@alice)', value: 'user:1', count: 10 })
      expect(options[2]).toEqual({ label: 'charlie', value: 'user:3', count: 2 })
    })

    it('has_mr filter returns yes/no options', async () => {
      await mountComponent()
      const mrField = (wrapper.vm as any).filterConfig.filterFields.find((f: any) => f.key === 'has_mr')
      const options = mrField.options()
      expect(options).toHaveLength(2)
      expect(options[0].value).toBe('true')
      expect(options[1].value).toBe('false')
    })

    it('rejects invalid URL values for status, project, and MR filters', async () => {
      await mountComponent()
      const fields = (wrapper.vm as any).filterConfig.filterFields

      expect(fields.find((field: any) => field.key === 'status').parseValue('bogus')).toBeUndefined()
      expect(fields.find((field: any) => field.key === 'project_id').parseValue('0')).toBeUndefined()
      expect(fields.find((field: any) => field.key === 'has_mr').parseValue('yes')).toBeUndefined()
    })
  })

  // -----------------------------------------------------------------------
  // 14. Pagination callbacks
  // -----------------------------------------------------------------------
  describe('pagination callbacks', () => {
    it('onUpdate:page changes page and fetches', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      const pag = wrapper.vm.pagination as any
      pag['onUpdate:page'](3)
      await flushPromises()

      expect(wrapper.vm.currentPage).toBe(3)
      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({ page: 3 }),
      )
    })

    it('onUpdate:pageSize changes size, resets page, and fetches', async () => {
      await mountComponent()
      mockApi.getIssues.mockClear()
      mockApi.getIssues.mockResolvedValue({ items: [], total: 0 })

      const pag = wrapper.vm.pagination as any
      pag['onUpdate:pageSize'](50)
      await flushPromises()

      expect(wrapper.vm.pageSize).toBe(50)
      expect(wrapper.vm.currentPage).toBe(1)
      expect(mockApi.getIssues).toHaveBeenCalledWith(
        expect.objectContaining({ page: 1, page_size: 50 }),
      )
    })

    it('pagination has correct initial values', async () => {
      await mountComponent()
      const pag = wrapper.vm.pagination as any
      expect(pag.page).toBe(1)
      expect(pag.pageSize).toBe(20)
      expect(pag.showSizePicker).toBe(true)
      expect(pag.pageSizes).toEqual([20, 50, 100])
    })
  })

  // -----------------------------------------------------------------------
  // 15. Helper functions
  // -----------------------------------------------------------------------
  describe('helper functions', () => {
    it('formatCompactDateTime returns dash for null', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatCompactDateTime(null)).toBe('-')
    })

    it('formatCompactDateTime returns dash for undefined', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatCompactDateTime(undefined)).toBe('-')
    })

    it('formatCompactDateTime returns dash for empty string', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatCompactDateTime('')).toBe('-')
    })

    it('formatCompactDateTime formats valid date string', async () => {
      await mountComponent()
      const result = (wrapper.vm as any).formatCompactDateTime('2024-06-15T12:30:00Z')
      expect(result).toBe('formatted-2024-06-15T12:30:00Z')
    })

    it('getProjectName returns name for known project', async () => {
      await mountComponent()
      expect((wrapper.vm as any).getProjectName(1)).toBe('group/project-1')
    })

    it('getProjectName returns fallback for unknown project', async () => {
      await mountComponent()
      expect((wrapper.vm as any).getProjectName(999)).toBe('Project #999')
    })

    it('formatNumber returns formatted value for integer', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatNumber(5)).toBe('5')
    })

    it('formatNumber returns dash for null', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatNumber(null)).toBe('—')
    })

    it('formatNumber returns dash for undefined', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatNumber(undefined)).toBe('—')
    })

    it('formatNumber returns dash for NaN', async () => {
      await mountComponent()
      expect((wrapper.vm as any).formatNumber(NaN)).toBe('—')
    })
  })

  // -----------------------------------------------------------------------
  // 16. Columns computed (visible filtering)
  // -----------------------------------------------------------------------
  describe('columns computed', () => {
    it('filters allColumns to only visible columns', async () => {
      await mountComponent()
      const allKeys = (wrapper.vm.allColumns as any[]).map((c: any) => c.key)
      const visibleKeys = (wrapper.vm.columns as any[]).map((c: any) => c.key)
      // initiator_username is not in mockFilterState.visibleColumns
      expect(allKeys).toContain('initiator_username')
      expect(visibleKeys).not.toContain('initiator_username')
      expect(visibleKeys).toContain('id')
      expect(visibleKeys).toContain('title')
      expect(visibleKeys).toContain('status')
    })
  })
})
