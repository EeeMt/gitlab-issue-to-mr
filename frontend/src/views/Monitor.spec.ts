import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import Monitor from './Monitor.vue'
import { createMockTask, createMockContainer } from '../test/mocks/api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage, resetMocks } = vi.hoisted(() => {
  const api = {
    getStats: vi.fn(),
    getContainers: vi.fn(),
    getTasks: vi.fn(),
    getTasksPaginated: vi.fn(),
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }
  const resetMocks = () => {
    Object.values(api).forEach(fn => fn.mockReset())
    Object.values(msg).forEach(fn => fn.mockReset())
  }
  return { mockApi: api, mockMessage: msg, resetMocks }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  getStats: mockApi.getStats,
  getContainers: mockApi.getContainers,
  getTasks: mockApi.getTasks,
  getTasksPaginated: mockApi.getTasksPaginated,
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((v: any) => `date:${v}`),
  formatTimeUtc8: vi.fn((v: any) => `time:${v}`),
  parseUtcDate: vi.fn((v: string) => new Date(v)),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string, params?: any) => {
      if (params) return `${key}:${JSON.stringify(params)}`
      return key
    }),
    locale: { value: 'en' },
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({
    push: vi.fn(),
  }),
}))

// ---------------------------------------------------------------------------
// Naive-UI mock
// ---------------------------------------------------------------------------
vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin--loading' : 'n-spin' }, slots.default?.())
    },
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'wrap', 'align', 'itemStyle'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary', 'size', 'text', 'ghost', 'strong', 'round'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () =>
        h(
          'button',
          {
            class: 'n-button',
            disabled: props.disabled || props.loading,
            onClick: () => emit('click'),
          },
          slots.default?.(),
        )
    },
  },
  NButtonGroup: {
    name: 'NButtonGroup',
    props: ['size'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-button-group' }, slots.default?.())
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size', 'title'],
    setup(_: any, { slots }: any) {
      return () =>
        h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    },
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap', 'responsive'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
  },
  NGi: {
    name: 'NGi',
    props: ['span'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
  },
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'animated'],
    emits: ['update:value'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-tabs' }, slots.default?.())
    },
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-tab-pane' }, slots.default?.())
    },
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'rowKey', 'bordered', 'scrollX', 'pagination', 'rowProps', 'singleLine', 'size', 'maxHeight'],
    setup(props: any) {
      return () =>
        h('div', { class: 'n-data-table', 'data-count': props.data?.length ?? 0 })
    },
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type', 'bordered'],
    setup(_: any, { slots }: any) {
      return () => h('span', { class: 'n-tag' }, slots.default?.())
    },
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description', 'showIcon', 'size'],
    setup(props: any) {
      return () => h('div', { class: 'n-empty' }, props.description)
    },
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-alert' }, slots.default?.())
    },
  },
  NText: {
    name: 'NText',
    props: ['depth', 'type'],
    setup(_: any, { slots }: any) {
      return () => h('span', { class: 'n-text' }, slots.default?.())
    },
  },
  useMessage: () => mockMessage,
}))

// ---------------------------------------------------------------------------
// Fixed time for deterministic assertions
// ---------------------------------------------------------------------------
const FIXED_NOW = new Date('2026-06-15T12:00:00Z').getTime()

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const defaultStats = {
  total: 42,
  pending: 5,
  queued: 3,
  running: 2,
  completed: 30,
  failed: 1,
  cancelled: 1,
  completed_24h: 15,
  failed_cancelled_24h: 2,
  running_long_30min: 0,
}

// Running task WITH a matching container
const runningTask1 = createMockTask({
  id: 1,
  status: 'running',
  priority: 1,
  container_id: 'ctr-1',
  container_name: 'codify-1-p1-i1',
  started_at: '2026-06-15T11:30:00Z', // exactly 30min ago — NOT long running (> 30min required)
  created_at: '2026-06-15T11:00:00Z',
  project_name: 'Project A',
  project_path_with_namespace: 'group/project-a',
})

// Running task WITHOUT a matching container
const runningTask2 = createMockTask({
  id: 2,
  status: 'running',
  priority: 1,
  container_id: 'ctr-missing',
  container_name: null,
  started_at: '2026-06-15T11:45:00Z', // 15min ago
  created_at: '2026-06-15T11:30:00Z',
  project_name: 'Project B',
  project_path_with_namespace: 'group/project-b',
})

// Pending task, no scheduled_at → ready (immediate)
const readyTask1 = createMockTask({
  id: 3,
  status: 'pending',
  priority: 1,
  scheduled_at: null,
  container_name: null,
  created_at: '2026-06-15T11:00:00Z',
  project_name: 'Project C',
  project_path_with_namespace: 'group/project-c',
})

// Queued task, past scheduled_at → ready
const readyTask2 = createMockTask({
  id: 4,
  status: 'queued',
  priority: 2,
  scheduled_at: '2026-06-15T11:00:00Z', // 1h in past
  container_name: null,
  created_at: '2026-06-15T10:30:00Z',
  project_name: 'Project D',
  project_path_with_namespace: 'group/project-d',
})

// Pending task, future scheduled_at → waiting
const waitingTask1 = createMockTask({
  id: 5,
  status: 'pending',
  priority: 1,
  scheduled_at: '2026-06-15T14:00:00Z', // 2h in the future
  container_name: null,
  created_at: '2026-06-15T10:00:00Z',
  project_name: 'Project E',
  project_path_with_namespace: 'group/project-e',
})

const mockActiveTasks = [runningTask1, runningTask2, readyTask1, readyTask2, waitingTask1]

const defaultContainers = [
  createMockContainer({ id: 'ctr-1', task_id: 1, status: 'running', name: 'codify-linked' }),
  createMockContainer({ id: 'ctr-2', task_id: null, status: 'running', name: 'codify-orphan-null' }),
  createMockContainer({ id: 'ctr-3', task_id: 999, status: 'running', name: 'codify-orphan-missing' }),
  createMockContainer({ id: 'ctr-4', task_id: 6, status: 'exited', name: 'codify-exited' }),
]

const emptyPaginated = { items: [], total: 0, page: 1, page_size: 10 }

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountComponent = () =>
  mount(Monitor, {
    global: {
      stubs: {
        PageHeader: {
          template: '<div class="page-header"><slot name="actions" /></div>',
        },
        SummaryCard: {
          props: ['label', 'value', 'note', 'cardClass', 'labelClass', 'valueClass', 'noteClass'],
          template: '<div class="summary-card"><span class="sc-label">{{ label }}</span><span class="sc-value">{{ value }}</span></div>',
        },
      },
    },
  })

// ---------------------------------------------------------------------------
// Setup helper
// ---------------------------------------------------------------------------
function setupDefaultMocks() {
  ;(mockApi.getStats as Mock).mockResolvedValue(defaultStats)
  ;(mockApi.getContainers as Mock).mockResolvedValue(defaultContainers)
  ;(mockApi.getTasks as Mock).mockResolvedValue(mockActiveTasks)
  ;(mockApi.getTasksPaginated as Mock).mockResolvedValue(emptyPaginated)
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('Monitor', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMocks()
    setupDefaultMocks()
    vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW)
    vi.spyOn(window, 'setInterval').mockImplementation(() => 42 as any)
    vi.spyOn(window, 'clearInterval').mockImplementation(() => {})
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
    vi.restoreAllMocks()
  })

  // =========================================================================
  // A. Initial Load & API Calls
  // =========================================================================
  describe('initial load & API calls', () => {
    it('calls all 5 API functions on mount (getStats, getContainers, getTasks, 2× getTasksPaginated)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
      expect(mockApi.getContainers).toHaveBeenCalledTimes(1)
      expect(mockApi.getTasks).toHaveBeenCalledTimes(1)
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(2)
    })

    it('calls getTasks with status filter for active tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(mockApi.getTasks).toHaveBeenCalledWith({ status: 'running,pending,queued' })
    })

    it('calls getTasksPaginated with correct params for finished and failed results', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({
        status: 'completed,failed,cancelled',
        page: 1,
        page_size: 10,
      })
      expect(mockApi.getTasksPaginated).toHaveBeenCalledWith({
        status: 'failed,cancelled',
        page: 1,
        page_size: 10,
      })
    })

    it('hasLoadedOnce starts false and becomes true after successful fetch', async () => {
      wrapper = mountComponent()
      expect(wrapper.vm.hasLoadedOnce).toBe(false)

      await flushPromises()
      expect(wrapper.vm.hasLoadedOnce).toBe(true)
    })

    it('loading starts true and becomes false after fetch completes', async () => {
      let resolveStats!: (v: any) => void
      ;(mockApi.getStats as Mock).mockReturnValue(new Promise(r => { resolveStats = r }))

      wrapper = mountComponent()
      await nextTick()

      expect(wrapper.vm.loading).toBe(true)
      expect(wrapper.vm.initialLoading).toBe(true)

      resolveStats(defaultStats)
      await flushPromises()

      expect(wrapper.vm.loading).toBe(false)
      expect(wrapper.vm.initialLoading).toBe(false)
    })
  })

  // =========================================================================
  // B. Computed Properties — Task Grouping
  // =========================================================================
  describe('computed — task grouping', () => {
    it('activeTasks includes only running/pending/queued tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const active = wrapper.vm.activeTasks as any[]
      expect(active).toHaveLength(5)
      expect(active.every((t: any) => ['running', 'pending', 'queued'].includes(t.status))).toBe(true)
    })

    it('activeTasks sorted: running first, then ready, then waiting', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const ids = (wrapper.vm.activeTasks as any[]).map((t: any) => t.id)
      // Running: 1,2 → Ready: 3 (P1 immediate), 4 (P2 past scheduled) → Waiting: 5
      expect(ids).toEqual([1, 2, 3, 4, 5])
    })

    it('runningTasks returns only tasks with status=running', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const running = wrapper.vm.runningTasks as any[]
      expect(running).toHaveLength(2)
      expect(running.every((t: any) => t.status === 'running')).toBe(true)
    })

    it('readyTasks returns pending/queued with scheduled_at <= now or null', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const ready = wrapper.vm.readyTasks as any[]
      expect(ready).toHaveLength(2)
      expect(ready.map((t: any) => t.id).sort()).toEqual([3, 4])
    })

    it('waitingTasks returns pending/queued with future scheduled_at', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const waiting = wrapper.vm.waitingTasks as any[]
      expect(waiting).toHaveLength(1)
      expect(waiting[0].id).toBe(5)
    })
  })

  // =========================================================================
  // C. Computed Properties — Container Analysis
  // =========================================================================
  describe('computed — container analysis', () => {
    it('runningContainers filters to containers with status=running', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const running = wrapper.vm.runningContainers as any[]
      // ctr-1, ctr-2, ctr-3 are running; ctr-4 is exited
      expect(running).toHaveLength(3)
      expect(running.every((c: any) => c.status === 'running')).toBe(true)
    })

    it('orphanContainers identifies running containers without a matching running task', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const orphans = wrapper.vm.orphanContainers as any[]
      // ctr-2: task_id=null → orphan; ctr-3: task_id=999 not found → orphan
      expect(orphans).toHaveLength(2)
      expect(orphans.map((c: any) => c.id).sort()).toEqual(['ctr-2', 'ctr-3'])
    })

    it('runningTasksWithoutContainer identifies running tasks with no matching running container', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const missing = wrapper.vm.runningTasksWithoutContainer as any[]
      // task 2: container_id='ctr-missing', no container has that id or task_id=2
      expect(missing).toHaveLength(1)
      expect(missing[0].id).toBe(2)
    })
  })

  // =========================================================================
  // D. Computed Properties — Health Checks
  // =========================================================================
  describe('computed — health checks', () => {
    it('healthChecks returns exactly 4 items (queue, workers, failures, runtime)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      expect(checks).toHaveLength(4)
      expect(checks.map((c: any) => c.key)).toEqual(['queue', 'workers', 'failures', 'runtime'])
    })

    it('queue health: success when backlog <= max(6, running*2)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const queue = checks.find((c: any) => c.key === 'queue')
      // backlog=3 (pending+queued tasks), running=2, max(6,4)=6 → 3<=6 → success
      expect(queue.type).toBe('success')
    })

    it('queue health: warning when backlog > max(6, running*2)', async () => {
      // Need backlog > max(6, 2*2)=6, so 7+ pending/queued tasks
      const manyTasks = [
        runningTask1,
        runningTask2,
        ...Array.from({ length: 7 }, (_, i) =>
          createMockTask({
            id: 10 + i,
            status: 'pending',
            container_name: null,
            created_at: `2026-06-15T0${i}:00:00Z`,
          }),
        ),
      ]
      ;(mockApi.getTasks as Mock).mockResolvedValue(manyTasks)

      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const queue = checks.find((c: any) => c.key === 'queue')
      expect(queue.type).toBe('warning')
    })

    it('worker health: warning when missing or orphaned containers > 0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const workers = checks.find((c: any) => c.key === 'workers')
      // 1 missing container + 2 orphaned = 3 > 0 → warning
      expect(workers.type).toBe('warning')
    })

    it('worker health: success when all containers aligned', async () => {
      const alignedTasks = [
        createMockTask({
          id: 1,
          status: 'running',
          container_id: 'ctr-1',
          container_name: null,
          started_at: '2026-06-15T11:30:00Z',
        }),
      ]
      const alignedContainers = [
        createMockContainer({ id: 'ctr-1', task_id: 1, status: 'running' }),
      ]
      ;(mockApi.getTasks as Mock).mockResolvedValue(alignedTasks)
      ;(mockApi.getContainers as Mock).mockResolvedValue(alignedContainers)

      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const workers = checks.find((c: any) => c.key === 'workers')
      expect(workers.type).toBe('success')
    })

    it('failure health: error when >2, warning when >0, success when =0', async () => {
      // — error scenario: failures24h > 2
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 3 })
      wrapper = mountComponent()
      await flushPromises()
      let checks = wrapper.vm.healthChecks as any[]
      expect(checks.find((c: any) => c.key === 'failures').type).toBe('error')
      wrapper.unmount()

      // — warning scenario: 0 < failures24h <= 2
      resetMocks()
      setupDefaultMocks()
      vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW)
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 1 })
      wrapper = mountComponent()
      await flushPromises()
      checks = wrapper.vm.healthChecks as any[]
      expect(checks.find((c: any) => c.key === 'failures').type).toBe('warning')
      wrapper.unmount()

      // — success scenario: failures24h = 0
      resetMocks()
      setupDefaultMocks()
      vi.spyOn(Date, 'now').mockReturnValue(FIXED_NOW)
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 0 })
      wrapper = mountComponent()
      await flushPromises()
      checks = wrapper.vm.healthChecks as any[]
      expect(checks.find((c: any) => c.key === 'failures').type).toBe('success')
    })

    it('runtime health: warning when long-running tasks exist (>30min)', async () => {
      const longRunning = createMockTask({
        id: 99,
        status: 'running',
        container_id: 'ctr-1',
        container_name: null,
        started_at: '2026-06-15T11:29:00Z', // 31min ago → exceeds 30min threshold
        created_at: '2026-06-15T11:00:00Z',
      })
      ;(mockApi.getTasks as Mock).mockResolvedValue([longRunning])

      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const runtime = checks.find((c: any) => c.key === 'runtime')
      expect(runtime.type).toBe('warning')
    })

    it('runtime health: success when no long-running tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const checks = wrapper.vm.healthChecks as any[]
      const runtime = checks.find((c: any) => c.key === 'runtime')
      // Both running tasks started ≤30min ago → success
      expect(runtime.type).toBe('success')
    })

    it('healthSummary: error when any check is error', async () => {
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 5 })

      wrapper = mountComponent()
      await flushPromises()

      expect((wrapper.vm.healthSummary as any).tagType).toBe('error')
    })

    it('healthSummary: warning when checks include warning but no error', async () => {
      // Worker check is warning (default data has orphans), failure check → 0 → success
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 0 })

      wrapper = mountComponent()
      await flushPromises()

      expect((wrapper.vm.healthSummary as any).tagType).toBe('warning')
    })

    it('healthSummary: success when all checks pass', async () => {
      // 1 pending task, no containers → no orphans/missing, no failures, no long-running
      const simpleTasks = [
        createMockTask({ id: 1, status: 'pending', container_name: null }),
      ]
      ;(mockApi.getTasks as Mock).mockResolvedValue(simpleTasks)
      ;(mockApi.getContainers as Mock).mockResolvedValue([])
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 0 })

      wrapper = mountComponent()
      await flushPromises()

      expect((wrapper.vm.healthSummary as any).tagType).toBe('success')
    })
  })

  // =========================================================================
  // E. Computed Properties — Cards
  // =========================================================================
  describe('computed — cards', () => {
    it('overviewCards has 4 items with correct values', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const cards = wrapper.vm.overviewCards as any[]
      expect(cards).toHaveLength(4)

      const running = cards.find((c: any) => c.key === 'running')
      expect(running.value).toBe('2') // 2 running tasks

      const backlog = cards.find((c: any) => c.key === 'backlog')
      expect(backlog.value).toBe('3') // 3 pending/queued tasks

      const containers = cards.find((c: any) => c.key === 'containers')
      expect(containers.value).toBe('3') // 3 running containers
    })

    it('runtimeCards has 4 items with correct metric values', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const cards = wrapper.vm.runtimeCards as any[]
      expect(cards).toHaveLength(4)

      expect(cards.find((c: any) => c.key === 'active').value).toBe('5')      // all active tasks
      expect(cards.find((c: any) => c.key === 'completed24h').value).toBe('15') // from stats
      expect(cards.find((c: any) => c.key === 'failures24h').value).toBe('2')   // from stats
      expect(cards.find((c: any) => c.key === 'longRunning').value).toBe('0')   // no long-running
    })
  })

  // =========================================================================
  // F. Data Refresh
  // =========================================================================
  describe('data refresh', () => {
    it('auto-refresh timer is registered on mount with 15s interval', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(window.setInterval).toHaveBeenCalledWith(expect.any(Function), 15000)
    })

    it('manual refresh button triggers fetchData', async () => {
      wrapper = mountComponent()
      await flushPromises()

      ;(mockApi.getStats as Mock).mockClear()
      ;(mockApi.getTasks as Mock).mockClear()
      ;(mockApi.getContainers as Mock).mockClear()
      ;(mockApi.getTasksPaginated as Mock).mockClear()

      const btn = wrapper.find('button.n-button')
      await btn.trigger('click')
      await flushPromises()

      expect(mockApi.getStats).toHaveBeenCalledTimes(1)
      expect(mockApi.getTasks).toHaveBeenCalledTimes(1)
      expect(mockApi.getContainers).toHaveBeenCalledTimes(1)
      expect(mockApi.getTasksPaginated).toHaveBeenCalledTimes(2)
    })

    it('concurrent refresh is prevented — second call queued until first finishes', async () => {
      let resolveFirst!: (v: any) => void
      ;(mockApi.getStats as Mock)
        .mockReturnValueOnce(new Promise(r => { resolveFirst = r }))
        .mockResolvedValue(defaultStats)

      wrapper = mountComponent()
      await nextTick()

      // First fetch is in-flight; trigger another visible refresh
      wrapper.vm.fetchData()
      await nextTick()

      // getStats called only once — the second request is queued
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)

      // Resolve first request → queued request fires automatically
      resolveFirst(defaultStats)
      await flushPromises()

      expect(mockApi.getStats).toHaveBeenCalledTimes(2)
    })
  })

  // =========================================================================
  // G. Error Handling
  // =========================================================================
  describe('error handling', () => {
    it('API error does not crash the component and shows error message', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      ;(mockApi.getStats as Mock).mockRejectedValue(new Error('Network error'))
      ;(mockApi.getContainers as Mock).mockRejectedValue(new Error('Network error'))
      ;(mockApi.getTasks as Mock).mockRejectedValue(new Error('Network error'))
      ;(mockApi.getTasksPaginated as Mock).mockRejectedValue(new Error('Network error'))

      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.exists()).toBe(true)
      expect(wrapper.vm.loading).toBe(false)
      expect(mockMessage.error).toHaveBeenCalled()
      consoleSpy.mockRestore()
    })

    it('hasLoadedOnce remains false on error (only set inside try block)', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      ;(mockApi.getStats as Mock).mockRejectedValue(new Error('fail'))
      ;(mockApi.getContainers as Mock).mockRejectedValue(new Error('fail'))
      ;(mockApi.getTasks as Mock).mockRejectedValue(new Error('fail'))
      ;(mockApi.getTasksPaginated as Mock).mockRejectedValue(new Error('fail'))

      wrapper = mountComponent()
      await flushPromises()

      // hasLoadedOnce is set inside try, so on error it stays false
      expect(wrapper.vm.hasLoadedOnce).toBe(false)
      consoleSpy.mockRestore()
    })
  })

  // =========================================================================
  // H. View Modes
  // =========================================================================
  describe('view modes', () => {
    it('default queueViewMode is kanban', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.queueViewMode).toBe('kanban')
    })

    it('can change queueViewMode to timeline and table', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.queueViewMode = 'timeline'
      await nextTick()
      expect(wrapper.vm.queueViewMode).toBe('timeline')

      wrapper.vm.queueViewMode = 'table'
      await nextTick()
      expect(wrapper.vm.queueViewMode).toBe('table')
    })
  })

  // =========================================================================
  // I. Empty States
  // =========================================================================
  describe('empty states', () => {
    it('empty tasks array results in empty activeTasks and shows NEmpty', async () => {
      ;(mockApi.getTasks as Mock).mockResolvedValue([])

      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.activeTasks).toHaveLength(0)
      expect(wrapper.find('.n-empty').exists()).toBe(true)
    })

    it('stats with all zeros renders overview cards correctly', async () => {
      ;(mockApi.getStats as Mock).mockResolvedValue({
        total: 0, pending: 0, queued: 0, running: 0,
        completed: 0, failed: 0, cancelled: 0,
        completed_24h: 0, failed_cancelled_24h: 0, running_long_30min: 0,
      })
      ;(mockApi.getTasks as Mock).mockResolvedValue([])
      ;(mockApi.getContainers as Mock).mockResolvedValue([])

      wrapper = mountComponent()
      await flushPromises()

      const overview = wrapper.vm.overviewCards as any[]
      expect(overview.find((c: any) => c.key === 'running').value).toBe('0')
      expect(overview.find((c: any) => c.key === 'backlog').value).toBe('0')
      expect(overview.find((c: any) => c.key === 'containers').value).toBe('0')
    })
  })

  // =========================================================================
  // J. Lifecycle / Cleanup
  // =========================================================================
  describe('lifecycle & cleanup', () => {
    it('registers both timers on mount (elapsed 1s + auto-refresh 15s)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // setInterval called for: auto-refresh (15s) + elapsed timer (1s)
      expect(window.setInterval).toHaveBeenCalledWith(expect.any(Function), 15000)
      expect(window.setInterval).toHaveBeenCalledWith(expect.any(Function), 1000)
    })

    it('timers are cleaned up on unmount (no leaks)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.unmount()
      wrapper = null

      // Both refreshTimer and elapsedTimer should be cleared
      expect(window.clearInterval).toHaveBeenCalled()
    })

    it('tableLoading is true when loading after first load has completed', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Now trigger a second fetch with a slow resolve
      let resolveSecond!: (v: any) => void
      ;(mockApi.getStats as Mock).mockReturnValue(new Promise(r => { resolveSecond = r }))

      wrapper.vm.fetchData()
      await nextTick()

      // hasLoadedOnce=true and loading=true → tableLoading=true
      expect(wrapper.vm.tableLoading).toBe(true)

      resolveSecond(defaultStats)
      await flushPromises()

      expect(wrapper.vm.tableLoading).toBe(false)
    })
  })
})
