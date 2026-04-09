import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import ScheduleOverview from './ScheduleOverview.vue'
import { createMockTask } from '../test/mocks/api'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage, resetMockApi } = vi.hoisted(() => {
  const api = {
    getScheduledStats: vi.fn(),
    getScheduledTasks: vi.fn(),
    rescheduleTask: vi.fn(),
    getConfig: vi.fn()
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
  getScheduledStats: mockApi.getScheduledStats,
  getScheduledTasks: mockApi.getScheduledTasks,
  rescheduleTask: mockApi.rescheduleTask,
  getConfig: mockApi.getConfig
}))

vi.mock('../auth', () => ({
  authState: { oidcEnabled: false },
  isAdmin: ref(true),
  initializeAuth: vi.fn().mockResolvedValue(undefined)
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((v: any) => `fmt:${v}`),
  formatMonthDayTimeUtc8: vi.fn((v: any) => `mdt:${v}`),
  formatMonthDayWeekdayUtc8: vi.fn((v: any) => `mdw:${v}`),
  formatTimeUtc8: vi.fn((v: any) => `time:${v}`),
  parseUtcDate: vi.fn((v: any) => new Date(v || Date.now()))
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: vi.fn() })
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string, params?: Record<string, unknown>) => {
      if (key === 'scheduleOverview.capacityLabel' && params) {
        return `${params.count}/${params.max}`
      }
      return key
    }),
    locale: { value: 'en' }
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: ref(1200) }))
}))

vi.mock('../components/HeatmapChart.vue', () => ({
  default: {
    name: 'HeatmapChart',
    props: ['tasks', 'selectedMs', 'maxPerSlot', 'enforceCapacity', 'allowFullSelection'],
    setup(props: any) {
      return () => h('div', {
        class: 'heatmap-chart-stub',
        'data-task-count': String(props.tasks?.length ?? 0),
        'data-selected-ms': props.selectedMs ?? '',
        'data-allow-full-selection': String(props.allowFullSelection ?? false)
      })
    }
  }
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
    props: ['type', 'loading', 'disabled', 'secondary', 'size', 'strong'],
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
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'rowKey', 'bordered', 'scrollX', 'pagination', 'rowProps'],
    setup(props: any) {
      return () => h('div', {
        class: 'n-data-table',
        'data-row-count': String(props.data?.length ?? 0)
      })
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
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    }
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'isDateDisabled', 'isTimeDisabled'],
    emits: ['update:value'],
    setup() { return () => h('div', { class: 'n-date-picker' }) }
  },
  NTabs: {
    name: 'NTabs',
    props: ['value'],
    emits: ['update:value'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tabs' }, slots.default?.()) }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-tab-pane' }, slots.default?.()) }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Mock data — tasks scheduled in the future
// ---------------------------------------------------------------------------
const futureTime = new Date(Date.now() + 60 * 60 * 1000).toISOString() // +1h
const laterTodayTime = new Date(Date.now() + 3 * 60 * 60 * 1000).toISOString() // +3h
const farFutureTime = new Date(Date.now() + 25 * 60 * 60 * 1000).toISOString() // +25h

const mockScheduledTasks = [
  createMockTask({ id: 1, status: 'queued', scheduled_at: futureTime, project_id: 1 }),
  createMockTask({ id: 2, status: 'queued', scheduled_at: farFutureTime, project_id: 2 }),
  createMockTask({ id: 3, status: 'running', scheduled_at: laterTodayTime, project_id: 1 })
]

const mockScheduledStats = {
  summary: {
    total: 3,
    ready_now: 1,
    next_24h: 2,
    later: 1,
    queued_count: 2,
    running_count: 1,
    busiest_hour_count: 1,
    busiest_hour_label: futureTime
  },
  hourly_distribution: [
    { hour_start: futureTime, count: 1 },
    { hour_start: laterTodayTime, count: 1 },
    { hour_start: farFutureTime, count: 1 }
  ],
  max_count: 1
}

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountComponent = () =>
  mount(ScheduleOverview, {
    global: {
      stubs: {
        SummaryCard: {
          props: ['label', 'value'],
          template: '<div class="summary-card"><span class="sc-label">{{ label }}</span><span class="sc-value">{{ value }}</span></div>'
        }
      }
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('ScheduleOverview', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    ;(mockApi.getScheduledStats as Mock).mockResolvedValue(mockScheduledStats)
    ;(mockApi.getScheduledTasks as Mock).mockResolvedValue(mockScheduledTasks)
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 0 } })
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
  it('calls scheduled stats and task APIs on mount', async () => {
    wrapper = mountComponent()
    await flushPromises()
    expect(mockApi.getScheduledStats).toHaveBeenCalledTimes(1)
    expect(mockApi.getScheduledTasks).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('shows loading spinner during initial fetch', async () => {
    let resolve!: (v: any) => void
    ;(mockApi.getScheduledStats as Mock).mockReturnValue(new Promise(r => { resolve = r }))

    wrapper = mountComponent()
    await nextTick()

    expect(wrapper.vm.initialLoading).toBe(true)
    expect(wrapper.vm.loading).toBe(true)

    resolve(mockScheduledStats)
    await flushPromises()

    expect(wrapper.vm.loading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('sets hasLoadedOnce after data loads', async () => {
    wrapper = mountComponent()
    expect(wrapper.vm.hasLoadedOnce).toBe(false)
    await flushPromises()
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('stores scheduled tasks in component state after load', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.scheduledTasks.length).toBe(3)
  })

  // -------------------------------------------------------------------------
  it('summary items are computed from scheduled stats', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    expect(items.length).toBeGreaterThan(0)
    // Each item should have label and value
    items.forEach((item: any) => {
      expect(item).toHaveProperty('label')
      expect(item).toHaveProperty('value')
    })
  })

  // -------------------------------------------------------------------------
  it('starts polling timer on mount', async () => {
    wrapper = mountComponent()
    await flushPromises()
    expect(window.setInterval).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('clears polling timer on unmount', async () => {
    wrapper = mountComponent()
    await flushPromises()

    wrapper.unmount()
    wrapper = null

    expect(window.clearInterval).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('refresh button triggers fetchData', async () => {
    wrapper = mountComponent()
    await flushPromises()

    ;(mockApi.getScheduledStats as Mock).mockClear()
    ;(mockApi.getScheduledTasks as Mock).mockClear()

    const btn = wrapper.find('button.n-button')
    await btn.trigger('click')
    await flushPromises()

    expect(mockApi.getScheduledStats).toHaveBeenCalledTimes(1)
    expect(mockApi.getScheduledTasks).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('handles fetch error gracefully', async () => {
    ;(mockApi.getScheduledStats as Mock).mockRejectedValue(new Error('Network error'))

    wrapper = mountComponent()
    await flushPromises()

    expect(mockMessage.error).toHaveBeenCalled()
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.vm.loading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('passes all scheduled tasks to the heatmap and hides the removed scheduled table card', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const heatmap = wrapper.find('.heatmap-chart-stub')
    expect(heatmap.attributes('data-task-count')).toBe('3')
    expect(heatmap.attributes('data-allow-full-selection')).toBe('true')
    expect(wrapper.html()).not.toContain('scheduleOverview.scheduledTasks')
  })

  // -------------------------------------------------------------------------
  it('derives selected window details from the loaded scheduled tasks', async () => {
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 5 } })

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
    await nextTick()

    expect(wrapper.vm.selectedWindowTasks).toHaveLength(1)
    expect(wrapper.vm.selectedWindowTasks[0].id).toBe(1)
    expect(wrapper.vm.selectedWindowLoadLabel).toBe('1/5')
  })

  // -------------------------------------------------------------------------
  it('reschedule updates the task in state on success', async () => {
    const updatedTask = createMockTask({
      id: 1,
      status: 'queued',
      scheduled_at: new Date(Date.now() + 2 * 60 * 60 * 1000).toISOString()
    })
    ;(mockApi.rescheduleTask as Mock).mockResolvedValue(updatedTask)

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
    await nextTick()

    // Set up a future draft timestamp
    const futureMs = Date.now() + 2 * 60 * 60 * 1000
    wrapper.vm.scheduleDrafts[1] = futureMs

    await wrapper.vm.handleTaskReschedule(mockScheduledTasks[0])
    await flushPromises()

    expect(mockApi.rescheduleTask).toHaveBeenCalledWith(1, expect.objectContaining({
      scheduled_datetime: expect.any(String)
    }))
    expect(mockApi.getScheduledStats).toHaveBeenCalledTimes(2)
    expect(mockApi.getScheduledTasks).toHaveBeenCalledTimes(2)
    expect(wrapper.vm.selectedWindow).toBe(null)
    expect(mockMessage.success).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('shows error when reschedule time is in the past', async () => {
    wrapper = mountComponent()
    await flushPromises()

    // Set a past timestamp
    wrapper.vm.scheduleDrafts[1] = Date.now() - 1000

    await wrapper.vm.handleTaskReschedule(mockScheduledTasks[0])

    expect(mockApi.rescheduleTask).not.toHaveBeenCalled()
    expect(mockMessage.error).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  // Slot capacity integration
  // -------------------------------------------------------------------------
  it('sets slotMaxTasks from config on load', async () => {
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 8 } })

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.slotMaxTasks).toBe(8)
  })

  it('defaults slotMaxTasks to 0 when config has no slot_max_tasks', async () => {
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: {} })

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.slotMaxTasks).toBe(0)
  })

  it('defaults slotMaxTasks to 0 when getConfig fails', async () => {
    ;(mockApi.getConfig as Mock).mockRejectedValue(new Error('config error'))

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.slotMaxTasks).toBe(0)
  })

  it('includes slot capacity in summaryItems when slotMaxTasks > 0', async () => {
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 5 } })

    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    const slotCapItem = items.find((i: any) => i.label === 'scheduleOverview.slotCapacity')
    expect(slotCapItem).toBeTruthy()
    expect(slotCapItem.value).toBe('5')
  })

  it('excludes slot capacity from summaryItems when slotMaxTasks = 0', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    const slotCapItem = items.find((i: any) => i.label === 'scheduleOverview.slotCapacity')
    expect(slotCapItem).toBeUndefined()
  })
})
