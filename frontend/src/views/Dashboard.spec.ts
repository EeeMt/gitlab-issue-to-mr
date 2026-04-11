import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Dashboard from './Dashboard.vue'
import { createMockTask, createMockProject } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getTasksPaginated: vi.fn<() => Promise<any>>(),
    getProjects: vi.fn<() => Promise<any[]>>(),
    getStats: vi.fn<() => Promise<any>>()
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => {
      if (typeof fn.mock !== 'undefined') {
        fn.mockReset()
      }
    })
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

// Mock i18n module
vi.mock('../i18n', () => ({
  currentLocale: ref('en')
}))

// Mock datetime utils
vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((value: any) => `formatted-date-${value}`)
}))

// Mock dependencies
vi.mock('../api', () => ({
  getTasksPaginated: mockApi.getTasksPaginated,
  getProjects: mockApi.getProjects,
  getStats: mockApi.getStats
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
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } }))
}))

// Mock naive-ui components
vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-spin-loading' }, slots.default?.()) : h('div', { class: 'n-spin' }, slots.default?.())
    },
    template: '<div class="n-spin"><slot /></div>'
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'wrap', 'align'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
    template: '<div class="n-space"><slot /></div>'
  },
  NSelect: {
    name: 'NSelect',
    props: ['options', 'loading', 'placeholder', 'disabled', 'value', 'clearable', 'filterable'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        disabled: props.disabled,
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    },
    template: '<select class="n-select"><option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option></select>'
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'secondary', 'strong', 'round', 'loading', 'disabled', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('button', {
        class: ['n-button', { loading: props.loading, disabled: props.disabled }],
        disabled: props.disabled || props.loading
      }, slots.default?.())
    },
    template: '<button class="n-button"><slot /></button>'
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [
        slots.header?.(),
        slots.default?.()
      ])
    },
    template: '<div class="n-card"><slot name="header" /><slot /></div>'
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'row-key', 'row-props', 'pagination', 'bordered', 'scroll-x'],
    setup(props: any) {
      return () => h('div', { class: 'n-data-table' }, props.data?.map((row: any) =>
        h('div', { class: 'n-data-table-row', 'data-id': row.id })
      ))
    },
    template: '<div class="n-data-table"><div v-for="row in data" :key="row.id" class="n-data-table-row">{{ row.id }}</div></div>'
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'x-gap', 'y-gap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
    template: '<div class="n-grid"><slot /></div>'
  },
  NGi: {
    name: 'NGi',
    props: [],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
    template: '<div class="n-gi"><slot /></div>'
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
    },
    template: '<span class="n-tag"><slot /></span>'
  },
  useMessage: () => mockMessage
}))

// Mock router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/tasks/:id', name: 'TaskView', component: { template: '<div>task</div>' } }
  ]
})

const mockTasks = [
  createMockTask({ id: 1, status: 'pending', initiator_username: 'user1', project_id: 1 }),
  createMockTask({ id: 2, status: 'running', initiator_username: 'user2', project_id: 1 }),
  createMockTask({ id: 3, status: 'completed', initiator_username: 'user1', project_id: 2 }),
  createMockTask({ id: 4, status: 'queued', initiator_username: 'user3', project_id: 1 }),
  createMockTask({ id: 5, status: 'failed', initiator_username: 'user2', project_id: 2 })
]

const mockProjects = [
  createMockProject({ id: 1, name: 'Project 1', path_with_namespace: 'group/project-1' }),
  createMockProject({ id: 2, name: 'Project 2', path_with_namespace: 'group/project-2' })
]

const mockStats = {
  total: 5,
  running: 1,
  completed: 1,
  pending: 1,
  queued: 1
}

describe('Dashboard', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    router.push('/')
    await router.isReady()

    // Mock document.visibilityState
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true
    })

    // Mock setInterval to capture the timer
    vi.spyOn(globalThis, 'setInterval').mockImplementation(() => 1 as ReturnType<typeof setInterval>)

    // Spy on clearInterval
    vi.spyOn(globalThis, 'clearInterval').mockImplementation(() => undefined)

    // Reset message mock
    Object.values(mockMessage).forEach(fn => fn.mockReset())
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.restoreAllMocks()
  })

  const mountComponent = async (tasks = mockTasks, projects = mockProjects, stats = mockStats) => {
    ;(mockApi.getTasksPaginated as Mock).mockResolvedValue({ items: tasks, total: tasks.length })
    ;(mockApi.getProjects as Mock).mockResolvedValue(projects)
    ;(mockApi.getStats as Mock).mockResolvedValue(stats)

    wrapper = mount(Dashboard, {
      global: {
        plugins: [router]
      }
    })

    // Wait for onMounted to complete
    await vi.waitFor(() => {
      return (mockApi.getTasksPaginated as Mock).mock.calls.length > 0
    })

    return wrapper
  }

  describe('basic rendering', () => {
    it('should render task list', async () => {
      await mountComponent()
      expect(wrapper.find('.dashboard').exists()).toBe(true)
    })

    it('should show loading state during initial fetch', async () => {
      let resolveTasks!: (value: { items: any[]; total: number }) => void
      const tasksPromise = new Promise<{ items: any[]; total: number }>(resolve => {
        resolveTasks = resolve
      })
      ;(mockApi.getTasksPaginated as Mock).mockReturnValue(tasksPromise)
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)

      wrapper = mount(Dashboard, {
        global: {
          plugins: [router]
        }
      })

      // Initial state - loading should be shown (initialLoading = loading && !hasLoadedOnce)
      expect(wrapper.vm.initialLoading).toBe(true)
      expect(wrapper.vm.loading).toBe(true)

      // Resolve the tasks
      resolveTasks({ items: mockTasks, total: mockTasks.length })

      // Wait for loading to complete
      await vi.waitFor(() => {
        return wrapper.vm.loading === false && wrapper.vm.hasLoadedOnce === true
      })

      expect(wrapper.vm.initialLoading).toBe(false)
    })

    it('should display summary cards after loading', async () => {
      await mountComponent()

      // Wait for hasLoadedOnce to become true
      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      // Summary cards should be visible
      expect(wrapper.find('.dashboard-summary-card').exists()).toBe(true)
    })

    it('should fetch tasks on mount', async () => {
      await mountComponent()
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    })

    it('should fetch projects on mount', async () => {
      await mountComponent()
      expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
    })
  })

  describe('filters', () => {
    it('should filter by status', async () => {
      await mountComponent()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.statusFilter = 'running'
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({ page: 1, page_size: 20, status: 'running' })
      })
    })

    it('should filter by project', async () => {
      await mountComponent()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.projectFilter = 1
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({ page: 1, page_size: 20, project_id: 1 })
      })
    })

    it('should filter by initiator', async () => {
      await mountComponent()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.initiatorFilter = 'user1'
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({ page: 1, page_size: 20, initiator_username: 'user1' })
      })
    })

    it('should combine multiple filters', async () => {
      await mountComponent()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.statusFilter = 'pending'
      wrapper.vm.projectFilter = 1
      wrapper.vm.initiatorFilter = 'user1'
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({
          page: 1,
          page_size: 20,
          status: 'pending',
          project_id: 1,
          initiator_username: 'user1'
        })
      })
    })

    it('should refetch tasks when filter changes', async () => {
      await mountComponent()

      // Initial fetch
      expect((mockApi.getTasksPaginated as Mock).mock.calls.length).toBe(1)

      // Change status filter
      wrapper.vm.statusFilter = 'completed'
      await nextTick()

      await vi.waitFor(() => {
        return (mockApi.getTasksPaginated as Mock).mock.calls.length >= 2
      })

      expect((mockApi.getTasksPaginated as Mock).mock.calls.length).toBeGreaterThanOrEqual(2)
    })
  })

  describe('auto-refresh', () => {
    it('should poll every 15 seconds', async () => {
      vi.useFakeTimers()

      await mountComponent()

      // Advance time by 15 seconds
      vi.advanceTimersByTime(15000)

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(2)
      })

      vi.useRealTimers()
    })

    it('should skip polling when tab not visible', async () => {
      vi.useFakeTimers()

      await mountComponent()

      // Make tab hidden
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true
      })

      // Advance time by 15 seconds
      vi.advanceTimersByTime(15000)

      // getTasksPaginated should only be called once (initial fetch)
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)

      vi.useRealTimers()
    })

    it('should resume polling when tab becomes visible', async () => {
      vi.useFakeTimers()

      await mountComponent()

      // Initial call count
      const initialCalls = (mockApi.getTasksPaginated as Mock).mock.calls.length

      // Make tab hidden and advance time
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        writable: true
      })
      vi.advanceTimersByTime(15000)
      expect((mockApi.getTasksPaginated as Mock).mock.calls.length).toBe(initialCalls)

      // Make tab visible again
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        writable: true
      })

      // Trigger next interval - when visibility becomes visible,
      // the next interval tick will fetch since the condition is checked inside the callback
      vi.advanceTimersByTime(15000)

      // After making visible and triggering interval, should fetch
      expect((mockApi.getTasksPaginated as Mock).mock.calls.length).toBe(initialCalls + 1)

      vi.useRealTimers()
    })

    it('should clear timer on unmount', async () => {
      vi.useFakeTimers()

      await mountComponent()

      // Advance time a bit
      vi.advanceTimersByTime(5000)

      const clearIntervalSpy = vi.spyOn(globalThis, 'clearInterval')

      wrapper.unmount()
      await nextTick()

      expect(clearIntervalSpy).toHaveBeenCalled()

      vi.useRealTimers()
    })
  })

  describe('task navigation', () => {
    it('should navigate to task view on row click', async () => {
      await mountComponent()

      const pushSpy = vi.spyOn(router, 'push')

      // Simulate row click via getRowProps
      const task = mockTasks[0]
      const props = wrapper.vm.getRowProps(task)

      // Trigger click handler manually (since event mocking is complex)
      props.onClick({ target: document.createElement('div') } as any)

      await vi.waitFor(() => {
        expect(pushSpy).toHaveBeenCalledWith({ name: 'TaskView', params: { id: task.id } })
      })
    })

    it('should not navigate when clicking interactive elements', async () => {
      await mountComponent()

      const pushSpy = vi.spyOn(router, 'push')

      // Simulate clicking on an interactive element (button)
      const button = document.createElement('button')
      const task = mockTasks[0]
      const props = wrapper.vm.getRowProps(task)

      props.onClick({ target: button } as unknown as MouseEvent)

      // push should not be called
      expect(pushSpy).not.toHaveBeenCalled()
    })

    it('should not navigate when clicking on links', async () => {
      await mountComponent()

      const pushSpy = vi.spyOn(router, 'push')

      // Simulate clicking on a link
      const link = document.createElement('a')
      const task = mockTasks[0]
      const props = wrapper.vm.getRowProps(task)

      props.onClick({ target: link } as unknown as MouseEvent)

      expect(pushSpy).not.toHaveBeenCalled()
    })
  })

  describe('responsive layout', () => {
    it('should use desktop columns by default', async () => {
      await mountComponent()

      // Default mock width is 1200, so isMobile should be false
      expect(wrapper.vm.isMobile).toBe(false)
      // Desktop has 11 columns
      expect(wrapper.vm.columns.length).toBe(11)
    })

    it('should have isMobile computed property', async () => {
      await mountComponent()

      // isMobile is a computed ref that depends on window width
      expect(typeof wrapper.vm.isMobile).toBe('boolean')
    })
  })

  describe('summary calculation', () => {
    it('should count total visible tasks', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const totalItem = wrapper.vm.summaryItems.find((item: any) => item.label === 'dashboard.visibleTasks')
      expect(totalItem.value).toBe(String(mockStats.total))
    })

    it('should count running tasks', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const runningItem = wrapper.vm.summaryItems.find((item: any) => item.label === 'dashboard.running')
      expect(runningItem.value).toBe(String(mockStats.running))
    })

    it('should count pending/queued tasks', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const pendingItem = wrapper.vm.summaryItems.find((item: any) => item.label === 'dashboard.pendingQueued')
      expect(pendingItem.value).toBe(String(mockStats.pending + mockStats.queued))
    })

    it('should count completed tasks', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const completedItem = wrapper.vm.summaryItems.find((item: any) => item.label === 'dashboard.completed')
      expect(completedItem.value).toBe(String(mockStats.completed))
    })

    it('should handle empty task list', async () => {
      await mountComponent([], mockProjects, { total: 0, running: 0, completed: 0, pending: 0, queued: 0 })

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const totalItem = wrapper.vm.summaryItems.find((item: any) => item.label === 'dashboard.visibleTasks')
      expect(totalItem.value).toBe('0')
    })

    it('should update visible task rows when filters change', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      // Mock the second call to return only 1 pending task
      const pendingTask = createMockTask({ id: 1, status: 'pending', initiator_username: 'user1', project_id: 1 })
      ;(mockApi.getTasksPaginated as Mock).mockResolvedValueOnce({ items: [pendingTask], total: 1 })

      // Change filter to get different tasks
      wrapper.vm.statusFilter = 'pending'
      await nextTick()

      await vi.waitFor(() => {
        return (mockApi.getTasksPaginated as Mock).mock.calls.length >= 2
      })

      // Wait for tasks to update
      await vi.waitFor(() => {
        return wrapper.vm.tasks.length === 1
      })

      expect(wrapper.vm.tasks).toHaveLength(1)
      expect(wrapper.vm.tasks[0].id).toBe(1)
    })
  })

  describe('refreshTasks', () => {
    it('should manually refresh tasks', async () => {
      await mountComponent()

      // Clear previous calls
      ;(mockApi.getTasksPaginated as Mock).mockClear()
      ;(mockApi.getStats as Mock).mockClear()

      wrapper.vm.refreshTasks()
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)
        expect(mockApi.getStats).toHaveBeenCalledTimes(1)
      })
    })

    it('should set loading state during refresh', async () => {
      await mountComponent()

      ;(mockApi.getTasksPaginated as Mock).mockImplementationOnce(
        () => new Promise(resolve => setTimeout(() => resolve({ items: mockTasks, total: mockTasks.length }), 100))
      )

      wrapper.vm.refreshTasks()

      // loading should be true
      await nextTick()
      expect(wrapper.vm.loading).toBe(true)

      // Wait for refresh to complete
      await vi.waitFor(() => {
        return wrapper.vm.loading === false
      })
    })
  })

  describe('error handling', () => {
    it('should handle fetch error gracefully', async () => {
      ;(mockApi.getTasksPaginated as Mock).mockRejectedValue(new Error('API Error'))
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)

      wrapper = mount(Dashboard, {
        global: {
          plugins: [router]
        }
      })

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      // Should have completed loading even with error
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
      expect(wrapper.vm.loading).toBe(false)
      // Should show error toast
      expect(mockMessage.error).toHaveBeenCalled()
    })
  })

  describe('initiatorOptions', () => {
    it('should extract unique initiators from tasks', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const options = wrapper.vm.initiatorOptions
      expect(options.map((o: any) => o.value)).toEqual(['user1', 'user2', 'user3'])
    })

    it('should sort initiators alphabetically', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.vm.hasLoadedOnce === true
      })

      const options = wrapper.vm.initiatorOptions
      const values = options.map((o: any) => o.value)
      expect(values).toEqual(['user1', 'user2', 'user3'])
    })

    it('should exclude tasks with null or empty initiator_username', async () => {
      const tasksWithGaps = [
        createMockTask({ id: 1, initiator_username: 'alice' }),
        createMockTask({ id: 2, initiator_username: null }),
        createMockTask({ id: 3, initiator_username: '' }),
        createMockTask({ id: 4, initiator_username: '  ' }),
        createMockTask({ id: 5, initiator_username: 'bob' })
      ]
      await mountComponent(tasksWithGaps)

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      const values = wrapper.vm.initiatorOptions.map((o: any) => o.value)
      expect(values).toEqual(['alice', 'bob'])
    })
  })

  describe('projectOptions', () => {
    it('should derive options from fetched projects', async () => {
      await mountComponent()

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      const options = wrapper.vm.projectOptions
      expect(options).toEqual([
        { label: 'group/project-1', value: 1 },
        { label: 'group/project-2', value: 2 }
      ])
    })

    it('should return empty array when no projects', async () => {
      await mountComponent(mockTasks, [])

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      expect(wrapper.vm.projectOptions).toEqual([])
    })
  })

  describe('pagination', () => {
    it('should update page and fetch tasks on page change', async () => {
      await mountComponent()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      const pag = wrapper.vm.pagination
      pag['onUpdate:page'](3)

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
          expect.objectContaining({ page: 3, page_size: 20 })
        )
      })
    })

    it('should update page size, reset to page 1, and fetch on page size change', async () => {
      await mountComponent()

      // first go to page 2
      wrapper.vm.pagination['onUpdate:page'](2)
      await vi.waitFor(() => wrapper.vm.currentPage === 2)

      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.pagination['onUpdate:pageSize'](50)

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1, page_size: 50 })
        )
      })
      expect(wrapper.vm.currentPage).toBe(1)
    })

    it('should expose pagination metadata', async () => {
      await mountComponent()

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      const pag = wrapper.vm.pagination
      expect(pag.page).toBe(1)
      expect(pag.pageSize).toBe(20)
      expect(pag.itemCount).toBe(mockTasks.length)
      expect(pag.pageSizes).toEqual([20, 50, 100])
      expect(pag.showSizePicker).toBe(true)
    })
  })

  describe('fetchTasks guard', () => {
    it('should skip fetch when already loading', async () => {
      let resolveTasks!: (value: { items: any[]; total: number }) => void
      const slowPromise = new Promise<{ items: any[]; total: number }>(resolve => {
        resolveTasks = resolve
      })
      ;(mockApi.getTasksPaginated as Mock).mockReturnValue(slowPromise)
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)

      wrapper = mount(Dashboard, {
        global: { plugins: [router] }
      })

      // First call is in-flight (loading = true)
      await nextTick()
      expect(wrapper.vm.loading).toBe(true)

      // Try to trigger another fetch while still loading
      wrapper.vm.refreshTasks()
      await nextTick()

      // Should still have only 1 call since guard prevents duplicate
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(1)

      // Resolve to avoid hanging promises
      resolveTasks({ items: mockTasks, total: mockTasks.length })
      await vi.waitFor(() => wrapper.vm.loading === false)
    })
  })

  describe('fetchStats error handling', () => {
    it('should handle stats API failure silently', async () => {
      ;(mockApi.getTasksPaginated as Mock).mockResolvedValue({ items: mockTasks, total: mockTasks.length })
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getStats as Mock).mockRejectedValue(new Error('Stats unavailable'))

      wrapper = mount(Dashboard, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      // Stats should remain at default values (0) — no crash
      expect(wrapper.vm.statsTotal).toBe(0)
      expect(wrapper.vm.statsRunning).toBe(0)
    })
  })

  describe('fetchProjects error handling', () => {
    it('should handle projects API failure silently', async () => {
      ;(mockApi.getTasksPaginated as Mock).mockResolvedValue({ items: mockTasks, total: mockTasks.length })
      ;(mockApi.getProjects as Mock).mockRejectedValue(new Error('Projects unavailable'))
      ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)

      wrapper = mount(Dashboard, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      // Projects should remain empty — no crash
      expect(wrapper.vm.projects).toEqual([])
      expect(wrapper.vm.projectOptions).toEqual([])
    })
  })

  describe('loading state', () => {
    it('tableLoading is true when loading AFTER first load', async () => {
      await mountComponent()
      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      // Simulate a slow refresh
      ;(mockApi.getTasksPaginated as Mock).mockImplementation(
        () => new Promise(resolve => setTimeout(() => resolve({ items: mockTasks, total: mockTasks.length }), 200))
      )

      wrapper.vm.refreshTasks()
      await nextTick()

      expect(wrapper.vm.tableLoading).toBe(true)
      expect(wrapper.vm.initialLoading).toBe(false)

      await vi.waitFor(() => wrapper.vm.loading === false)
    })

    it('initialLoading is true only before first load completes', async () => {
      let resolveTasks!: (value: any) => void
      const slowPromise = new Promise(resolve => { resolveTasks = resolve })

      ;(mockApi.getTasksPaginated as Mock).mockReturnValue(slowPromise)
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)

      wrapper = mount(Dashboard, { global: { plugins: [router] } })
      await nextTick()

      expect(wrapper.vm.initialLoading).toBe(true)
      expect(wrapper.vm.tableLoading).toBe(false)

      resolveTasks({ items: mockTasks, total: mockTasks.length })
      await vi.waitFor(() => wrapper.vm.hasLoadedOnce === true)

      expect(wrapper.vm.initialLoading).toBe(false)
    })
  })

  describe('isInteractiveTarget', () => {
    it('should return false for non-Element target', async () => {
      await mountComponent()

      const result = wrapper.vm.isInteractiveTarget(null)
      expect(result).toBe(false)
    })

    it('should return false for non-Element text node', async () => {
      await mountComponent()

      const textNode = document.createTextNode('hello')
      const result = wrapper.vm.isInteractiveTarget(textNode)
      expect(result).toBe(false)
    })

    it('should return true for input elements', async () => {
      await mountComponent()

      const input = document.createElement('input')
      expect(wrapper.vm.isInteractiveTarget(input)).toBe(true)
    })

    it('should return true for element nested inside a link', async () => {
      await mountComponent()

      const anchor = document.createElement('a')
      const span = document.createElement('span')
      anchor.appendChild(span)
      document.body.appendChild(anchor)

      expect(wrapper.vm.isInteractiveTarget(span)).toBe(true)

      document.body.removeChild(anchor)
    })
  })

  describe('desktop column render functions', () => {
    // Helper: find a desktop column by key and call its render function
    const getColumnRender = (columns: any[], key: string) => {
      const col = columns.find((c: any) => c.key === key)
      return col?.render
    }

    it('renderStatus produces NTag with correct type per status', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'status')
      expect(render).toBeDefined()

      const pending = render(createMockTask({ status: 'pending' }))
      expect(pending.type).toBeDefined() // VNode for NTag
      expect(pending.props.type).toBe('default')

      const running = render(createMockTask({ status: 'running' }))
      expect(running.props.type).toBe('warning')

      const completed = render(createMockTask({ status: 'completed' }))
      expect(completed.props.type).toBe('success')

      const failed = render(createMockTask({ status: 'failed' }))
      expect(failed.props.type).toBe('error')

      const queued = render(createMockTask({ status: 'queued' }))
      expect(queued.props.type).toBe('info')
    })

    it('project column renders project label and ID', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'project')
      expect(render).toBeDefined()

      const task = createMockTask({ project_id: 42, project_path_with_namespace: 'org/repo' })
      const vnode = render(task)

      // The top-level vnode is a div; check its children contain project info
      expect(vnode.children).toBeDefined()
      expect(vnode.children.length).toBe(2)

      // Second child should contain the project ID text
      const idDiv = vnode.children[1]
      expect(idDiv.children).toContain('ID: 42')
    })

    it('initiator column renders username', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'initiator_username')
      expect(render).toBeDefined()

      expect(render(createMockTask({ initiator_username: 'alice' }))).toBe('alice')
    })

    it('initiator column renders dash for null username', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'initiator_username')
      expect(render(createMockTask({ initiator_username: null }))).toBe('-')
    })

    it('issue column renders link when issue_iid present', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'issue_iid')
      expect(render).toBeDefined()

      const task = createMockTask({ issue_iid: 99, issue_url: 'https://example.com/issue/99' })
      const vnode = render(task)
      expect(vnode.props.href).toBe('https://example.com/issue/99')
      expect(vnode.children).toBe('!99')
    })

    it('issue column renders dash when no issue_iid', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'issue_iid')
      const result = render(createMockTask({ issue_iid: null }))
      expect(result).toBe('-')
    })

    it('priority column formats priority value', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'priority')
      expect(render).toBeDefined()

      expect(render(createMockTask({ priority: 0 }))).toBe('P0')
      expect(render(createMockTask({ priority: 1 }))).toBe('P1')
      expect(render(createMockTask({ priority: 2 }))).toBe('P2')
    })

    it('branch column renders link when branch exists', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'branch_name')
      expect(render).toBeDefined()

      const task = createMockTask({ branch_name: 'feat/x', branch_url: 'https://example.com/tree/feat/x' })
      const vnode = render(task)
      expect(vnode.props.href).toBe('https://example.com/tree/feat/x')
      expect(vnode.children).toBe('feat/x')
    })

    it('branch column renders dash when no branch', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'branch_name')
      const result = render(createMockTask({ branch_name: null }))
      expect(result).toBe('-')
    })

    it('merge_request column renders link with MR iid', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'merge_request_url')
      expect(render).toBeDefined()

      const task = createMockTask({
        merge_request_url: 'https://example.com/mr/5',
        merge_request_iid: 5
      })
      const vnode = render(task)
      expect(vnode.props.href).toBe('https://example.com/mr/5')
      expect(vnode.children).toBe('!5')
    })

    it('merge_request column renders "open" label when no iid', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'merge_request_url')
      const task = createMockTask({
        merge_request_url: 'https://example.com/mr/new',
        merge_request_iid: null
      })
      const vnode = render(task)
      expect(vnode.props.href).toBe('https://example.com/mr/new')
      expect(vnode.children).toBe('dashboard.open')
    })

    it('merge_request column renders dash when no URL', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'merge_request_url')
      const result = render(createMockTask({ merge_request_url: null }))
      expect(result).toBe('-')
    })

    it('changes column renders additions and deletions', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'changes')
      expect(render).toBeDefined()

      const task = createMockTask({ additions: 10, deletions: 5 })
      const vnode = render(task)
      // Should render a span with two child spans
      expect(vnode.type).toBe('span')
      expect(vnode.children.length).toBe(2)
      expect(vnode.children[0].children).toBe('+10')
      expect(vnode.children[1].children).toBe('-5')
    })

    it('changes column renders with zero additions but nonzero deletions', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'changes')
      const task = createMockTask({ additions: 0, deletions: 7 })
      const vnode = render(task)
      expect(vnode.type).toBe('span')
      expect(vnode.children[0].children).toBe('+0')
      expect(vnode.children[1].children).toBe('-7')
    })

    it('changes column renders with nonzero additions but zero deletions', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'changes')
      const task = createMockTask({ additions: 3, deletions: 0 })
      const vnode = render(task)
      expect(vnode.type).toBe('span')
      expect(vnode.children[0].children).toBe('+3')
      expect(vnode.children[1].children).toBe('-0')
    })

    it('changes column renders dash when both are zero', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'changes')
      const result = render(createMockTask({ additions: 0, deletions: 0 }))
      expect(result).toBe('-')
    })

    it('changes column renders dash when both are undefined', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'changes')
      const task = createMockTask({})
      // Remove the additions/deletions properties to simulate undefined
      delete (task as any).additions
      delete (task as any).deletions
      const result = render(task)
      expect(result).toBe('-')
    })

    it('created_at column formats date string', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'created_at')
      expect(render).toBeDefined()

      const task = createMockTask({ created_at: '2026-01-15T08:30:00Z' })
      const result = render(task)
      expect(result).toBe('formatted-date-2026-01-15T08:30:00Z')
    })

    it('scheduled_at column returns dash for null', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'scheduled_at')
      expect(render).toBeDefined()

      const task = createMockTask({ scheduled_at: null })
      const result = render(task)
      expect(result).toBe('-')
    })

    it('scheduled_at column formats date when present', async () => {
      await mountComponent()

      const render = getColumnRender(wrapper.vm.columns, 'scheduled_at')
      const task = createMockTask({ scheduled_at: '2026-06-01T12:00:00Z' })
      const result = render(task)
      expect(result).toBe('formatted-date-2026-06-01T12:00:00Z')
    })
  })

  describe('mobile columns', () => {
    it('should use mobile columns when screen width is below breakpoint', async () => {
      // Override the window size mock to return mobile width
      const { useWindowSize } = await import('@vueuse/core')
      ;(useWindowSize as any).mockReturnValue({ width: { value: 500 } })

      await mountComponent()

      expect(wrapper.vm.isMobile).toBe(true)
      // Mobile has 3 columns: id, task_info, status
      expect(wrapper.vm.columns.length).toBe(3)
      expect(wrapper.vm.columns.map((c: any) => c.key)).toEqual(['id', 'task_info', 'status'])

      // Restore desktop width
      ;(useWindowSize as any).mockReturnValue({ width: { value: 1200 } })
    })

    it('mobile task_info column renders project label and branch', async () => {
      const { useWindowSize } = await import('@vueuse/core')
      ;(useWindowSize as any).mockReturnValue({ width: { value: 500 } })

      await mountComponent()

      const render = wrapper.vm.columns.find((c: any) => c.key === 'task_info')?.render
      expect(render).toBeDefined()

      const task = createMockTask({
        project_path_with_namespace: 'org/repo',
        issue_iid: 10,
        branch_name: 'feat/login',
        branch_url: 'https://example.com/tree/feat/login'
      })
      const vnode = render(task)
      expect(vnode.type).toBe('div')
      expect(vnode.children.length).toBe(2)

      // Restore desktop width
      ;(useWindowSize as any).mockReturnValue({ width: { value: 1200 } })
    })

    it('mobile task_info renders dash for missing branch', async () => {
      const { useWindowSize } = await import('@vueuse/core')
      ;(useWindowSize as any).mockReturnValue({ width: { value: 500 } })

      await mountComponent()

      const render = wrapper.vm.columns.find((c: any) => c.key === 'task_info')?.render
      const task = createMockTask({ branch_name: null })
      const vnode = render(task)
      // Second child (branch div) should contain '-'
      expect(vnode.children[1].children).toBe('-')

      // Restore desktop width
      ;(useWindowSize as any).mockReturnValue({ width: { value: 1200 } })
    })
  })

  describe('helper functions', () => {
    it('renderExternalLink returns anchor when href is provided', async () => {
      await mountComponent()

      const vnode = wrapper.vm.renderExternalLink('Click me', 'https://example.com')
      expect(vnode.type).toBe('a')
      expect(vnode.props.href).toBe('https://example.com')
      expect(vnode.props.target).toBe('_blank')
      expect(vnode.children).toBe('Click me')
    })

    it('renderExternalLink returns plain label when href is null', async () => {
      await mountComponent()

      const result = wrapper.vm.renderExternalLink('Label only', null)
      expect(result).toBe('Label only')
    })

    it('renderExternalLink returns plain label when href is undefined', async () => {
      await mountComponent()

      const result = wrapper.vm.renderExternalLink('Label only', undefined)
      expect(result).toBe('Label only')
    })

    it('getProjectSecondaryLabel includes issue iid when present', async () => {
      await mountComponent()

      const task = createMockTask({
        project_path_with_namespace: 'org/repo',
        issue_iid: 42
      })
      const label = wrapper.vm.getProjectSecondaryLabel(task)
      expect(label).toContain('org/repo')
      expect(label).toContain('!42')
    })

    it('getProjectSecondaryLabel shows dash when no issue_iid', async () => {
      await mountComponent()

      const task = createMockTask({
        project_path_with_namespace: 'org/repo',
        issue_iid: null
      })
      const label = wrapper.vm.getProjectSecondaryLabel(task)
      expect(label).toContain('org/repo')
      expect(label).toContain('-')
    })

    it('getInitiatorLabel returns trimmed username', async () => {
      await mountComponent()

      const task = createMockTask({ initiator_username: '  alice  ' })
      expect(wrapper.vm.getInitiatorLabel(task)).toBe('alice')
    })

    it('getInitiatorLabel returns dash for null username', async () => {
      await mountComponent()

      const task = createMockTask({ initiator_username: null })
      expect(wrapper.vm.getInitiatorLabel(task)).toBe('-')
    })

    it('formatCompactDateTime returns formatted date for valid value', async () => {
      await mountComponent()

      const result = wrapper.vm.formatCompactDateTime('2026-01-01T00:00:00Z')
      expect(result).toBe('formatted-date-2026-01-01T00:00:00Z')
    })

    it('formatCompactDateTime returns dash for null', async () => {
      await mountComponent()

      expect(wrapper.vm.formatCompactDateTime(null)).toBe('-')
    })

    it('formatCompactDateTime returns dash for undefined', async () => {
      await mountComponent()

      expect(wrapper.vm.formatCompactDateTime(undefined)).toBe('-')
    })

    it('getProjectLabel returns path_with_namespace when available', async () => {
      await mountComponent()

      const task = createMockTask({ project_path_with_namespace: 'org/repo', project_name: 'repo' })
      expect(wrapper.vm.getProjectLabel(task)).toBe('org/repo')
    })

    it('getProjectLabel returns project_name as fallback', async () => {
      await mountComponent()

      const task = createMockTask({
        project_path_with_namespace: null,
        project_name: 'repo'
      })
      expect(wrapper.vm.getProjectLabel(task)).toBe('repo')
    })

    it('getProjectLabel returns i18n fallback when no names', async () => {
      await mountComponent()

      const task = createMockTask({
        project_path_with_namespace: null,
        project_name: null,
        project_id: 99
      })
      const label = wrapper.vm.getProjectLabel(task)
      expect(label).toBe('dashboard.projectFallback')
    })
  })

  describe('filter watcher resets page', () => {
    it('should reset to page 1 when status filter changes from a later page', async () => {
      await mountComponent()

      // Simulate being on page 3
      wrapper.vm.currentPage = 3
      await nextTick()

      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.statusFilter = 'failed'
      await nextTick()

      await vi.waitFor(() => {
        expect(mockApi.getTasksPaginated).toHaveBeenCalledWith(
          expect.objectContaining({ page: 1 })
        )
      })
      expect(wrapper.vm.currentPage).toBe(1)
    })

    it('should reset to page 1 when project filter changes', async () => {
      await mountComponent()

      wrapper.vm.currentPage = 2
      await nextTick()

      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.projectFilter = 1
      await nextTick()

      await vi.waitFor(() => {
        expect(wrapper.vm.currentPage).toBe(1)
      })
    })

    it('should reset to page 1 when initiator filter changes', async () => {
      await mountComponent()

      wrapper.vm.currentPage = 5
      await nextTick()

      ;(mockApi.getTasksPaginated as Mock).mockClear()

      wrapper.vm.initiatorFilter = 'user1'
      await nextTick()

      await vi.waitFor(() => {
        expect(wrapper.vm.currentPage).toBe(1)
      })
    })
  })

  describe('statusOptions', () => {
    it('should provide all 6 status filter options', async () => {
      await mountComponent()

      const options = wrapper.vm.statusOptions
      expect(options).toHaveLength(6)
      expect(options.map((o: any) => o.value)).toEqual([
        'pending', 'queued', 'running', 'completed', 'failed', 'cancelled'
      ])
    })
  })

  describe('getRowProps', () => {
    it('should set cursor pointer style', async () => {
      await mountComponent()

      const props = wrapper.vm.getRowProps(mockTasks[0])
      expect(props.style).toBe('cursor: pointer;')
    })

    it('should not navigate when clicking on select element', async () => {
      await mountComponent()
      const pushSpy = vi.spyOn(router, 'push')

      const select = document.createElement('select')
      const task = mockTasks[0]
      const props = wrapper.vm.getRowProps(task)
      props.onClick({ target: select } as unknown as MouseEvent)

      expect(pushSpy).not.toHaveBeenCalled()
    })
  })
})
