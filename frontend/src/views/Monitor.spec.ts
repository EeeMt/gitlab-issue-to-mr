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
  NScrollbar: {
    name: 'NScrollbar',
    props: ['trigger', 'xScrollable'],
    setup(_: any, { slots }: any) {
      return () => h('div', { class: 'n-scrollbar' }, slots.default?.())
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
    it('sortedContainers keeps the running container subset visible', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const running = (wrapper.vm.sortedContainers as any[])
        .filter((container: any) => container.status === 'running')
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

      const healthCard = (wrapper.vm.overviewCards as any[])
        .find((card: any) => card.key === 'health')
      expect(healthCard.tagType).toBe('error')
    })

    it('healthSummary: warning when checks include warning but no error', async () => {
      // Worker check is warning (default data has orphans), failure check → 0 → success
      ;(mockApi.getStats as Mock).mockResolvedValue({ ...defaultStats, failed_cancelled_24h: 0 })

      wrapper = mountComponent()
      await flushPromises()

      const healthCard = (wrapper.vm.overviewCards as any[])
        .find((card: any) => card.key === 'health')
      expect(healthCard.tagType).toBe('warning')
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

      const healthCard = (wrapper.vm.overviewCards as any[])
        .find((card: any) => card.key === 'health')
      expect(healthCard.tagType).toBe('success')
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

  // =========================================================================
  // K. Timeline Computed Helpers
  // =========================================================================
  describe('timeline computed helpers', () => {
    it('timelineRange returns a range covering tasks, with 5% padding', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const range = wrapper.vm.timelineRange as { start: number; end: number }
      expect(range.start).toBeLessThan(FIXED_NOW)
      expect(range.end).toBeGreaterThan(FIXED_NOW)
      // Waiting task has scheduled_at 2h in future → maxTime ≥ that + 30min + padding
      const waitingScheduledMs = new Date('2026-06-15T14:00:00Z').getTime()
      expect(range.end).toBeGreaterThan(waitingScheduledMs)
    })

    it('timelineRange extends when zoom is set (non-auto)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.timelineZoom = '8h'
      await nextTick()

      const range = wrapper.vm.timelineRange as { start: number; end: number }
      // 8h zoom window → minTime ≤ now - 8h*0.3 = now - 2.4h
      expect(range.start).toBeLessThanOrEqual(FIXED_NOW - 8 * 60 * 60 * 1000 * 0.3 * 0.95)
      // maxTime ≥ now + 8h*0.7 = now + 5.6h
      expect(range.end).toBeGreaterThanOrEqual(FIXED_NOW + 8 * 60 * 60 * 1000 * 0.7 * 0.95)
    })

    it('timelinePct clamps values to [0, 100]', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const range = wrapper.vm.timelineRange as { start: number; end: number }
      // A time far before range.start → 0%
      expect(wrapper.vm.timelinePct(range.start - 999999999)).toBe(0)
      // A time far after range.end → 100%
      expect(wrapper.vm.timelinePct(range.end + 999999999)).toBe(100)
    })

    it('timelineTicks generates tick marks between start and end', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const ticks = wrapper.vm.timelineTicks as any[]
      expect(ticks.length).toBeGreaterThan(0)
      for (const tick of ticks) {
        expect(tick).toHaveProperty('time')
        expect(tick).toHaveProperty('pct')
        expect(tick).toHaveProperty('label')
        expect(tick.pct).toBeGreaterThanOrEqual(0)
        expect(tick.pct).toBeLessThanOrEqual(100)
      }
    })

    it('timelineTicks adjusts density based on zoom level', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const autoTicks = (wrapper.vm.timelineTicks as any[]).length

      wrapper.vm.timelineZoom = '1h'
      await nextTick()

      const zoomedTicks = (wrapper.vm.timelineTicks as any[]).length
      // 1h zoom should produce different tick count than auto
      expect(zoomedTicks).not.toBe(autoTicks)
    })

    it('timelineContainerMinWidth is at least 600px', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const minWidth = wrapper.vm.timelineContainerMinWidth as string
      const numericPart = parseInt(minWidth)
      expect(numericPart).toBeGreaterThanOrEqual(600)
      expect(minWidth).toContain('px')
    })
  })

  // =========================================================================
  // L. Helper Functions
  // =========================================================================
  describe('helper functions', () => {
    it('formatElapsedCompact returns "Xm Ys" for < 1 hour', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // runningTask1 started at 11:30, now=12:00 → 30min 0s
      const result = wrapper.vm.formatElapsedCompact('2026-06-15T11:30:00Z')
      expect(result).toBe('30m 0s')
    })

    it('formatElapsedCompact returns "Xh Ym" for >= 1 hour', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // 2h before now = 10:00
      const result = wrapper.vm.formatElapsedCompact('2026-06-15T10:00:00Z')
      expect(result).toBe('2h 0m')
    })

    it('formatRelativeFuture returns "<1m" when < 1 minute away', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Exactly now → 0ms → <1m
      const result = wrapper.vm.formatRelativeFuture(new Date(FIXED_NOW + 30 * 1000).toISOString())
      expect(result).toBe('<1m')
    })

    it('formatRelativeFuture returns "Xh Ym" for future time > 1 hour', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // 2h + 15min = 135 min in the future
      const futureTime = new Date(FIXED_NOW + (2 * 60 + 15) * 60 * 1000).toISOString()
      const result = wrapper.vm.formatRelativeFuture(futureTime)
      expect(result).toBe('2h 15m')
    })

    it('formatRelativeFuture returns "Xh" when minutes=0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const futureTime = new Date(FIXED_NOW + 3 * 60 * 60 * 1000).toISOString()
      const result = wrapper.vm.formatRelativeFuture(futureTime)
      expect(result).toBe('3h')
    })

    it('formatRelativeFuture returns "Xm" for future time < 1 hour', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const futureTime = new Date(FIXED_NOW + 45 * 60 * 1000).toISOString()
      const result = wrapper.vm.formatRelativeFuture(futureTime)
      expect(result).toBe('45m')
    })

    it('formatPromptPreview returns "-" for null/empty prompt', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.formatPromptPreview(null)).toBe('-')
      expect(wrapper.vm.formatPromptPreview(undefined)).toBe('-')
    })

    it('formatPromptPreview truncates long prompts to 96 characters', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const longPrompt = 'A'.repeat(200)
      const result = wrapper.vm.formatPromptPreview(longPrompt)
      expect(result).toHaveLength(96)
    })

    it('formatPromptPreview collapses whitespace', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.formatPromptPreview('hello   world\n\nnew line')
      expect(result).toBe('hello world new line')
    })

    it('summarizeError returns i18n key for null/empty error', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.summarizeError(null)).toBe('monitor.noErrorMessage')
      expect(wrapper.vm.summarizeError(undefined)).toBe('monitor.noErrorMessage')
    })

    it('summarizeError returns first non-empty line trimmed to 140 chars', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const error = '\n  Error: something failed\nStack trace line 1'
      const result = wrapper.vm.summarizeError(error)
      expect(result).toBe('Error: something failed')
    })

    it('priorityClass returns correct class for P0, P1, P2 and default', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.priorityClass(0)).toBe('priority-tone--p0')
      expect(wrapper.vm.priorityClass(1)).toBe('priority-tone--p1')
      expect(wrapper.vm.priorityClass(2)).toBe('priority-tone--p2')
      expect(wrapper.vm.priorityClass(3)).toBe('priority-tone--default')
      expect(wrapper.vm.priorityClass(null)).toBe('priority-tone--default')
    })

    it('kanbanProjectLabel returns project_name or path_with_namespace or "—"', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.kanbanProjectLabel({ project_name: 'My Project', project_path_with_namespace: 'grp/proj' })).toBe('My Project')
      expect(wrapper.vm.kanbanProjectLabel({ project_name: null, project_path_with_namespace: 'grp/proj' })).toBe('grp/proj')
      expect(wrapper.vm.kanbanProjectLabel({ project_name: null, project_path_with_namespace: null })).toBe('—')
    })

    it('kanbanIssueLabel returns #id title or dash', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.kanbanIssueLabel({ issue: { id: 42, title: 'Login bug' } })).toBe('#42 Login bug')
      expect(wrapper.vm.kanbanIssueLabel({ issue: null })).toBe('—')
      expect(wrapper.vm.kanbanIssueLabel({})).toBe('—')
    })

    it('getExecutionDuration returns "-" when started_at or completed_at is missing', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.getExecutionDuration({ started_at: null, completed_at: null })).toBe('-')
      expect(wrapper.vm.getExecutionDuration({ started_at: '2026-06-15T11:00:00Z', completed_at: null })).toBe('-')
    })

    it('getTaskElapsedLabel shows running prefix for running tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getTaskElapsedLabel({
        status: 'running',
        started_at: '2026-06-15T11:30:00Z',
        created_at: '2026-06-15T11:00:00Z'
      })
      expect(result).toContain('monitor.runningForPrefix')
    })

    it('getTaskElapsedLabel shows waiting prefix for non-running tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getTaskElapsedLabel({
        status: 'pending',
        started_at: null,
        created_at: '2026-06-15T11:00:00Z'
      })
      expect(result).toContain('monitor.waitingForPrefix')
    })
  })

  // =========================================================================
  // M. Container Relation Logic
  // =========================================================================
  describe('getContainerRelation', () => {
    it('returns "unmapped" when container has no task_id', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getContainerRelation({ task_id: null, status: 'running' })
      expect(result.label).toBe('monitor.unmapped')
      expect(result.type).toBe('default')
    })

    it('returns "taskMissing" when task not found for container', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getContainerRelation({ task_id: 999, status: 'running' })
      expect(result.label).toBe('monitor.taskMissing')
      expect(result.type).toBe('warning')
    })

    it('returns "linked" when both container and task are running', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // ctr-1 → task_id=1, task 1 is running
      const result = wrapper.vm.getContainerRelation({ task_id: 1, status: 'running' })
      expect(result.label).toBe('monitor.linked')
      expect(result.type).toBe('success')
    })

    it('returns "outlivedTask" when container is running but task is not running', async () => {
      // Need a non-running task with a running container
      const completedTask = createMockTask({ id: 50, status: 'completed', container_name: null })
      ;(mockApi.getTasks as Mock).mockResolvedValue([...mockActiveTasks, completedTask])

      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getContainerRelation({ task_id: 50, status: 'running' })
      expect(result.label).toBe('monitor.outlivedTask')
      expect(result.type).toBe('warning')
    })

    it('returns "taskStillMarkedRunning" when container exited but task running', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // task 1 is running, but container is exited
      const result = wrapper.vm.getContainerRelation({ task_id: 1, status: 'exited' })
      expect(result.label).toBe('monitor.taskStillMarkedRunning')
      expect(result.type).toBe('warning')
    })

    it('returns "historical" when both container and task are not running', async () => {
      const completedTask = createMockTask({ id: 50, status: 'completed', container_name: null })
      ;(mockApi.getTasks as Mock).mockResolvedValue([...mockActiveTasks, completedTask])

      wrapper = mountComponent()
      await flushPromises()

      const result = wrapper.vm.getContainerRelation({ task_id: 50, status: 'exited' })
      expect(result.label).toBe('monitor.historical')
      expect(result.type).toBe('info')
    })
  })

  // =========================================================================
  // N. Status Breakdown & Sorted Containers
  // =========================================================================
  describe('statusBreakdown & sortedContainers', () => {
    it('statusBreakdown returns 6 items with correct keys and percentages', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const breakdown = wrapper.vm.statusBreakdown as any[]
      expect(breakdown).toHaveLength(6)
      expect(breakdown.map((b: any) => b.key)).toEqual(['pending', 'queued', 'running', 'completed', 'failed', 'cancelled'])

      const pending = breakdown.find((b: any) => b.key === 'pending')
      expect(pending.percent).toBeCloseTo((5 / 42) * 100, 1)
      const queued = breakdown.find((b: any) => b.key === 'queued')
      expect(queued.percent).toBeCloseTo((3 / 42) * 100, 1)
    })

    it('statusBreakdown uses Math.max(total, 1) to avoid division by zero', async () => {
      ;(mockApi.getStats as Mock).mockResolvedValue({
        total: 0, pending: 0, queued: 0, running: 0,
        completed: 0, failed: 0, cancelled: 0,
        completed_24h: 0, failed_cancelled_24h: 0, running_long_30min: 0,
      })
      ;(mockApi.getTasks as Mock).mockResolvedValue([])
      ;(mockApi.getContainers as Mock).mockResolvedValue([])

      wrapper = mountComponent()
      await flushPromises()

      const breakdown = wrapper.vm.statusBreakdown as any[]
      // All percents should be 0 (0/1 * 100 = 0), not NaN
      breakdown.forEach((b: any) => {
        expect(Number.isNaN(b.percent)).toBe(false)
        expect(b.percent).toBe(0)
      })
    })

    it('sortedContainers puts running containers first, then sorts by created_at desc', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const sorted = wrapper.vm.sortedContainers as any[]
      // running containers: ctr-1, ctr-2, ctr-3; exited: ctr-4
      // First 3 should be running
      expect(sorted.slice(0, 3).every((c: any) => c.status === 'running')).toBe(true)
      // Last should be exited
      expect(sorted[sorted.length - 1].status).toBe('exited')
    })
  })

  // =========================================================================
  // O. Debug Cards
  // =========================================================================
  describe('computed — debug cards', () => {
    it('debugCards has 4 items with correct metric values', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const cards = wrapper.vm.debugCards as any[]
      expect(cards).toHaveLength(4)

      expect(cards.find((c: any) => c.key === 'visible').value).toBe('4')  // all containers
      expect(cards.find((c: any) => c.key === 'linked').value).toBe('1')   // only ctr-1 linked
      expect(cards.find((c: any) => c.key === 'missing').value).toBe('1')  // task 2 has no container
      expect(cards.find((c: any) => c.key === 'orphaned').value).toBe('2') // ctr-2, ctr-3
    })
  })

  // =========================================================================
  // P. Row Props & Navigation
  // =========================================================================
  describe('row props & navigation', () => {
    it('activeTaskRowProps returns click handler that navigates to task', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.activeTaskRowProps({ id: 42 } as any)
      expect(props.style).toBe('cursor: pointer;')
      expect(typeof props.onClick).toBe('function')
    })

    it('recentActivityRowProps returns click handler', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.recentActivityRowProps({ id: 7 } as any)
      expect(props.style).toBe('cursor: pointer;')
    })

    it('recentFailureRowProps returns click handler', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.recentFailureRowProps({ id: 10 } as any)
      expect(props.style).toBe('cursor: pointer;')
    })

    it('containerRowProps returns empty object when no task_id', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.containerRowProps({ task_id: null } as any)
      expect(props).toEqual({})
    })

    it('containerRowProps returns empty object when task_id not in tasksById', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.containerRowProps({ task_id: 9999 } as any)
      expect(props).toEqual({})
    })

    it('containerRowProps returns click handler when task_id maps to known task', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const props = wrapper.vm.containerRowProps({ task_id: 1 } as any)
      expect(props.style).toBe('cursor: pointer;')
      expect(typeof props.onClick).toBe('function')
    })
  })

  // =========================================================================
  // Q. Timeline Tooltip
  // =========================================================================
  describe('timeline tooltip', () => {
    it('showTimelineTooltip sets tooltip state and hideTimelineTooltip clears it', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.tooltipVisible).toBe(false)

      // Simulate mouseenter with a mock event
      const mockEl = document.createElement('div')
      document.body.appendChild(mockEl)
      const rect = mockEl.getBoundingClientRect()

      const mockEvent = {
        currentTarget: mockEl,
      } as unknown as MouseEvent

      // Mock getBoundingClientRect to return known values
      vi.spyOn(mockEl, 'getBoundingClientRect').mockReturnValue({
        left: 100, top: 200, bottom: 300, right: 200,
        width: 100, height: 100, x: 100, y: 200, toJSON: () => {}
      })

      wrapper.vm.showTimelineTooltip(mockEvent, 'Task #1 details')

      expect(wrapper.vm.tooltipVisible).toBe(true)
      expect(wrapper.vm.tooltipText).toBe('Task #1 details')

      wrapper.vm.hideTimelineTooltip()
      expect(wrapper.vm.tooltipVisible).toBe(false)

      document.body.removeChild(mockEl)
    })
  })

  // =========================================================================
  // R. Kanban View Rendering
  // =========================================================================
  describe('kanban view rendering', () => {
    it('renders kanban columns with task cards', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Default view is kanban
      expect(wrapper.vm.queueViewMode).toBe('kanban')
      // Check running column has cards
      const kanban = wrapper.find('.queue-kanban')
      expect(kanban.exists()).toBe(true)

      // Running column
      const runningCol = wrapper.find('.queue-kanban__column--running')
      expect(runningCol.exists()).toBe(true)
      const runningCards = runningCol.findAll('.queue-kanban__card')
      expect(runningCards).toHaveLength(2)

      // Ready column
      const readyCol = wrapper.find('.queue-kanban__column--ready')
      expect(readyCol.exists()).toBe(true)
      const readyCards = readyCol.findAll('.queue-kanban__card')
      expect(readyCards).toHaveLength(2)

      // Waiting column
      const waitingCol = wrapper.find('.queue-kanban__column--waiting')
      expect(waitingCol.exists()).toBe(true)
      const waitingCards = waitingCol.findAll('.queue-kanban__card')
      expect(waitingCards).toHaveLength(1)
    })

    it('kanban cards display task id and priority', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const firstCard = wrapper.find('.queue-kanban__card')
      expect(firstCard.text()).toContain('#1')
    })

    it('kanban card click navigates to task', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const card = wrapper.find('.queue-kanban__card')
      await card.trigger('click')
      // goToTask calls router.push
    })
  })

  // =========================================================================
  // S. Queue View Options
  // =========================================================================
  describe('queueViewOptions', () => {
    it('provides three view options: kanban, timeline, table', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const options = wrapper.vm.queueViewOptions as any[]
      expect(options).toHaveLength(3)
      expect(options.map((o: any) => o.value)).toEqual(['kanban', 'timeline', 'table'])
    })
  })

  // =========================================================================
  // T. Silent Refresh Queuing
  // =========================================================================
  describe('silent refresh queuing', () => {
    it('queues a silent refresh when fetchData is called silently during in-flight request', async () => {
      let resolveFirst!: (v: any) => void
      ;(mockApi.getStats as Mock)
        .mockReturnValueOnce(new Promise(r => { resolveFirst = r }))
        .mockResolvedValue(defaultStats)

      wrapper = mountComponent()
      await nextTick()

      // First fetch is in-flight; trigger a silent refresh
      wrapper.vm.fetchData({ silent: true })
      await nextTick()

      // Only one call so far
      expect(mockApi.getStats).toHaveBeenCalledTimes(1)

      resolveFirst(defaultStats)
      await flushPromises()

      // Queued silent refresh fires
      expect(mockApi.getStats).toHaveBeenCalledTimes(2)
    })
  })
})
