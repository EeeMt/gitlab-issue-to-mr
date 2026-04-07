import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import Dashboard from './Dashboard.vue'
import { createMockTask, createMockProject } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi } = vi.hoisted(() => {
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
  return { mockApi: mock, resetMockApi }
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
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  })
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
  })
})
