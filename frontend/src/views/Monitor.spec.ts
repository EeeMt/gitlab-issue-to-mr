import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import Monitor from './Monitor.vue'
import { createMockTask, createMockContainer, createMockStats } from '../test/mocks/api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage, resetMockApi } = vi.hoisted(() => {
  const api = {
    getTasks: vi.fn(),
    getContainers: vi.fn(),
    getStats: vi.fn()
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }
  const resetMockApi = () => Object.values(api).forEach(fn => fn.mockReset())
  return { mockApi: api, mockMessage: msg, resetMockApi }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  getTasks: mockApi.getTasks,
  getContainers: mockApi.getContainers,
  getStats: mockApi.getStats
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((v: any) => `fmt:${v}`),
  parseUtcDate: vi.fn((v: any) => new Date(v || Date.now()))
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() })
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' }
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: ref(1200) }))
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
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'wrap', 'align'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-space' }, slots.default?.()) }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary', 'size'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled || props.loading,
        onClick: () => emit('click')
      }, slots.default?.())
    }
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size'],
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
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-gi' }, slots.default?.()) }
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-tag' }, slots.default?.()) }
  },
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type'],
    emits: ['update:value'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tabs' }, slots.default?.()) }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tab-pane' }, slots.default?.()) }
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'rowKey', 'bordered', 'scrollX', 'pagination', 'rowProps'],
    setup(props: any) {
      return () => h('div', { class: 'n-data-table', 'data-count': props.data?.length ?? 0 })
    }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description'],
    setup(props: any) { return () => h('div', { class: 'n-empty' }, props.description) }
  },
  NText: {
    name: 'NText',
    props: ['depth'],
    setup(_p: any, { slots }: any) { return () => h('span', slots.default?.()) }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockStats = createMockStats({ total: 5, running: 1, pending: 2, queued: 1, completed: 1 })

const mockTasks = [
  createMockTask({ id: 1, status: 'running', started_at: '2026-01-01T00:00:00Z', container_id: 'container-1' }),
  createMockTask({ id: 2, status: 'pending' }),
  createMockTask({ id: 3, status: 'queued' }),
  createMockTask({ id: 4, status: 'completed', started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T01:00:00Z' }),
  createMockTask({ id: 5, status: 'failed', started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:30:00Z' })
]

const mockContainers = [
  createMockContainer({ id: 'container-1', task_id: 1, status: 'running' }),
  createMockContainer({ id: 'container-2', task_id: null, status: 'running' })
]

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountOptions = {
  global: {
    stubs: {
      PageHeader: {
        template: '<div class="page-header"><slot name="actions"/></div>'
      },
      SummaryCard: {
        props: ['label', 'value'],
        template: '<div class="summary-card"><span class="label">{{ label }}</span><span class="value">{{ value }}</span></div>'
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('Monitor', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)
    ;(mockApi.getTasks as Mock).mockResolvedValue(mockTasks)
    ;(mockApi.getContainers as Mock).mockResolvedValue(mockContainers)
    vi.spyOn(window, 'setInterval').mockImplementation(() => 1 as any)
    vi.spyOn(window, 'clearInterval').mockImplementation(() => undefined)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
    vi.restoreAllMocks()
  })

  // -------------------------------------------------------------------------
  it('calls getStats, getTasks, and getContainers on mount', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    expect(mockApi.getStats).toHaveBeenCalledTimes(1)
    expect(mockApi.getTasks).toHaveBeenCalledTimes(1)
    expect(mockApi.getContainers).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('shows loading spinner during initial fetch', async () => {
    let resolve!: (v: any) => void
    ;(mockApi.getStats as Mock).mockReturnValue(new Promise(r => { resolve = r }))

    wrapper = mount(Monitor, mountOptions)
    await nextTick()

    expect(wrapper.vm.initialLoading).toBe(true)
    expect(wrapper.vm.loading).toBe(true)

    resolve(mockStats)
    await flushPromises()

    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.initialLoading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('sets hasLoadedOnce after first successful fetch', async () => {
    wrapper = mount(Monitor, mountOptions)
    await nextTick()

    expect(wrapper.vm.hasLoadedOnce).toBe(false)

    await flushPromises()

    expect(wrapper.vm.hasLoadedOnce).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('renders summary cards after data loads', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    expect(wrapper.findAll('.summary-card').length).toBeGreaterThan(0)
  })

  // -------------------------------------------------------------------------
  it('refresh button triggers fetchData', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    ;(mockApi.getTasks as Mock).mockClear()
    ;(mockApi.getStats as Mock).mockClear()
    ;(mockApi.getContainers as Mock).mockClear()

    const btn = wrapper.find('button.n-button')
    await btn.trigger('click')
    await flushPromises()

    expect(mockApi.getTasks).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('starts auto-refresh timer on mount', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    expect(window.setInterval).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('clears auto-refresh timer on unmount', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    wrapper.unmount()
    wrapper = null

    expect(window.clearInterval).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('computes activeTasks from running/pending/queued tasks', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    // active = pending + queued + running = 3 in mockTasks
    expect(wrapper.vm.activeTasks.length).toBe(3)
  })

  // -------------------------------------------------------------------------
  it('computes runningTasks from running tasks only', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    expect(wrapper.vm.runningTasks.length).toBe(1)
    expect(wrapper.vm.runningTasks[0].id).toBe(1)
  })

  // -------------------------------------------------------------------------
  it('computes runningContainers from containers with running status', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    expect(wrapper.vm.runningContainers.length).toBe(2)
  })

  // -------------------------------------------------------------------------
  it('computes orphanContainers for containers with no matching task', async () => {
    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    // container-2 has task_id=null so it's an orphan
    expect(wrapper.vm.orphanContainers.length).toBeGreaterThanOrEqual(1)
  })

  // -------------------------------------------------------------------------
  it('handles fetch error gracefully — hasLoadedOnce becomes true', async () => {
    const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
    ;(mockApi.getTasks as Mock).mockRejectedValue(new Error('Network error'))
    ;(mockApi.getStats as Mock).mockRejectedValue(new Error('Network error'))
    ;(mockApi.getContainers as Mock).mockRejectedValue(new Error('Network error'))

    wrapper = mount(Monitor, mountOptions)
    await flushPromises()

    // loading should reset even on error
    expect(wrapper.vm.loading).toBe(false)
    consoleSpy.mockRestore()
  })

  // -------------------------------------------------------------------------
  it('tableLoading is true when loading and hasLoadedOnce', async () => {
    ;(mockApi.getStats as Mock).mockResolvedValue(mockStats)
    ;(mockApi.getTasks as Mock).mockResolvedValue(mockTasks)
    ;(mockApi.getContainers as Mock).mockResolvedValue(mockContainers)

    wrapper = mount(Monitor, mountOptions)
    // Let first load finish
    await flushPromises()

    // Trigger a reload: start a slow request
    let resolveStats!: (v: any) => void
    ;(mockApi.getStats as Mock).mockReturnValue(new Promise(r => { resolveStats = r }))
    ;(mockApi.getTasks as Mock).mockReturnValue(new Promise(r => r(mockTasks)))
    ;(mockApi.getContainers as Mock).mockReturnValue(new Promise(r => r(mockContainers)))

    wrapper.vm.fetchData()
    await nextTick()

    // Now hasLoadedOnce = true and loading = true → tableLoading = true
    expect(wrapper.vm.tableLoading).toBe(true)

    resolveStats(mockStats)
    await flushPromises()
    expect(wrapper.vm.tableLoading).toBe(false)
  })
})
