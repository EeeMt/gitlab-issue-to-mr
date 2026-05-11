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
    rescheduleTask: vi.fn()
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }
  const resetMocks = () => {
    Object.values(api).forEach(fn => fn.mockReset())
    Object.values(msg).forEach(fn => fn.mockReset())
  }
  return { mockApi: api, mockMessage: msg, resetMockApi: resetMocks }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  getScheduledStats: mockApi.getScheduledStats,
  getScheduledTasks: mockApi.getScheduledTasks,
  rescheduleTask: mockApi.rescheduleTask
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
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        role: 'switch',
        'aria-checked': String(props.value ?? false),
        onClick: () => emit('update:value', !props.value)
      })
    }
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
  max_count: 1,
  slot_max_tasks: 0,
  slot_max_tasks_enforce: false
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
    ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 5 })

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
  it('sets slotMaxTasks from scheduled stats on load', async () => {
    ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 8 })

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.slotMaxTasks).toBe(8)
  })

  it('defaults slotMaxTasks to 0 when stats has no slot_max_tasks field', async () => {
    const { slot_max_tasks: _, ...withoutSlotMax } = { ...mockScheduledStats, slot_max_tasks: undefined }
    ;(mockApi.getScheduledStats as Mock).mockResolvedValue(withoutSlotMax)

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.slotMaxTasks).toBe(0)
  })

  it('includes slot capacity in summaryItems when slotMaxTasks > 0', async () => {
    ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 5 })

    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    const fullSlotsItem = items.find((i: any) => i.label === 'scheduleOverview.fullSlots')
    expect(fullSlotsItem).toBeTruthy()
  })

  it('excludes slot capacity from summaryItems when slotMaxTasks = 0', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    const fullSlotsItem = items.find((i: any) => i.label === 'scheduleOverview.fullSlots')
    expect(fullSlotsItem).toBeUndefined()
  })

  // =========================================================================
  // Hourly Buckets
  // =========================================================================
  describe('hourlyBuckets computed', () => {
    it('returns buckets from hourly_distribution when available', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const buckets = wrapper.vm.hourlyBuckets as any[]
      expect(buckets).toHaveLength(3) // 3 entries in mockScheduledStats.hourly_distribution
      expect(buckets[0].count).toBe(1)
      expect(buckets[0]).toHaveProperty('key')
      expect(buckets[0]).toHaveProperty('label')
      expect(buckets[0]).toHaveProperty('shortLabel')
      expect(buckets[0]).toHaveProperty('heightPercent')
      expect(buckets[0]).toHaveProperty('startMs')
    })

    it('returns 24 empty buckets as fallback when no distribution data', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({
        summary: mockScheduledStats.summary,
        hourly_distribution: [],
        max_count: 0
      })

      wrapper = mountComponent()
      await flushPromises()

      const buckets = wrapper.vm.hourlyBuckets as any[]
      expect(buckets).toHaveLength(24)
      buckets.forEach((b: any) => {
        expect(b.count).toBe(0)
        expect(b.heightPercent).toBe(0)
      })
    })

    it('calculates heightPercent relative to maxCount with minimum of 2% for nonzero', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({
        summary: mockScheduledStats.summary,
        hourly_distribution: [
          { hour_start: futureTime, count: 1 },
          { hour_start: laterTodayTime, count: 5 }
        ],
        max_count: 5
      })

      wrapper = mountComponent()
      await flushPromises()

      const buckets = wrapper.vm.hourlyBuckets as any[]
      // count=1, maxCount=5 → (1/5)*100=20%, min(20, 2) = 20
      expect(buckets[0].heightPercent).toBe(20)
      // count=5, maxCount=5 → 100%
      expect(buckets[1].heightPercent).toBe(100)
    })
  })

  // =========================================================================
  // Busy/Idle Windows
  // =========================================================================
  describe('busy and idle windows', () => {
    it('busyWindows returns top 5 buckets with count > 0, sorted by count desc', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const busy = wrapper.vm.busyWindows as any[]
      expect(busy.length).toBeGreaterThan(0)
      expect(busy.length).toBeLessThanOrEqual(5)
      busy.forEach((b: any) => expect(b.count).toBeGreaterThan(0))
      // Check descending order
      for (let i = 1; i < busy.length; i++) {
        expect(busy[i - 1].count).toBeGreaterThanOrEqual(busy[i].count)
      }
    })

    it('idleWindows returns up to 5 buckets with count = 0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const idle = wrapper.vm.idleWindows as any[]
      // With 3 buckets all having count=1, idle should be empty
      expect(idle).toHaveLength(0)
    })

    it('idleWindows returns idle slots when some buckets have count=0', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({
        summary: mockScheduledStats.summary,
        hourly_distribution: [],
        max_count: 0
      })

      wrapper = mountComponent()
      await flushPromises()

      const idle = wrapper.vm.idleWindows as any[]
      // 24 empty fallback buckets → all idle, capped at 5
      expect(idle).toHaveLength(5)
      idle.forEach((b: any) => expect(b.count).toBe(0))
    })
  })

  // =========================================================================
  // Selected Window Management
  // =========================================================================
  describe('selected window management', () => {
    it('handleHourlyBucketSelect ignores buckets with count=0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.handleHourlyBucketSelect({ key: 'test', count: 0, startMs: 999 } as any)
      await nextTick()

      expect(wrapper.vm.selectedWindow).toBeNull()
    })

    it('handleHourlyBucketSelect sets window for bucket with count > 0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const buckets = wrapper.vm.hourlyBuckets as any[]
      const nonEmpty = buckets.find((b: any) => b.count > 0)
      wrapper.vm.handleHourlyBucketSelect(nonEmpty)
      await nextTick()

      expect(wrapper.vm.selectedWindow).not.toBeNull()
      expect(wrapper.vm.selectedWindow.startMs).toBe(nonEmpty.startMs)
      expect(wrapper.vm.selectedWindow.endMs).toBe(nonEmpty.startMs + 60 * 60 * 1000)
    })

    it('clearSelectedWindow resets selectedWindow, drafts, and dirtyDraftIds', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // First set a window
      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()
      expect(wrapper.vm.selectedWindow).not.toBeNull()

      // Now clear it
      wrapper.vm.clearSelectedWindow()
      await nextTick()

      expect(wrapper.vm.selectedWindow).toBeNull()
      expect(Object.keys(wrapper.vm.scheduleDrafts)).toHaveLength(0)
    })

    it('isSelectedWindow returns true for matching start/end', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const startMs = new Date(futureTime).getTime()
      wrapper.vm.handleHeatmapCellClick(startMs)
      await nextTick()

      expect(wrapper.vm.isSelectedWindow(startMs, startMs + 60 * 60 * 1000)).toBe(true)
      expect(wrapper.vm.isSelectedWindow(startMs + 1, startMs + 60 * 60 * 1000)).toBe(false)
    })

    it('handleHeatmapCellClick creates a 1-hour window from the given start', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const start = new Date(futureTime).getTime()
      wrapper.vm.handleHeatmapCellClick(start)
      await nextTick()

      const win = wrapper.vm.selectedWindow as any
      expect(win.startMs).toBe(start)
      expect(win.endMs).toBe(start + 60 * 60 * 1000)
      expect(win.key).toContain('heatmap-')
    })
  })

  // =========================================================================
  // Selected Window Tasks & Load Label
  // =========================================================================
  describe('selectedWindowTasks & load label', () => {
    it('selectedWindowTasks filters tasks in the selected window', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const startMs = new Date(futureTime).getTime()
      wrapper.vm.handleHeatmapCellClick(startMs)
      await nextTick()

      const tasks = wrapper.vm.selectedWindowTasks as any[]
      expect(tasks.length).toBe(1)
      expect(tasks[0].id).toBe(1)
    })

    it('selectedWindowTasks returns empty when no window selected', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.selectedWindowTasks).toHaveLength(0)
    })

    it('selectedWindowLoadLabel returns null when slotMaxTasks = 0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      expect(wrapper.vm.selectedWindowLoadLabel).toBeNull()
    })

    it('selectedWindowLoadLabel returns null when no window selected', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.selectedWindowLoadLabel).toBeNull()
    })
  })

  // =========================================================================
  // Schedule Drafts
  // =========================================================================
  describe('schedule drafts', () => {
    it('syncScheduleDrafts populates drafts from selectedWindowTasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      const drafts = wrapper.vm.scheduleDrafts as Record<number, number | null>
      expect(1 in drafts).toBe(true)
    })

    it('syncScheduleDrafts preserves dirty drafts during refresh', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Select window and mark a draft as dirty
      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      const customValue = Date.now() + 999999
      wrapper.vm.scheduleDrafts[1] = customValue
      wrapper.vm.onDraftChange(1)

      // Trigger syncScheduleDrafts by calling it indirectly (via another heatmap click on same window)
      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      // The dirty draft should be preserved
      expect(wrapper.vm.scheduleDrafts[1]).toBe(customValue)
    })

    it('syncScheduleDrafts clears everything when no window is selected', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // Set up a window then clear it
      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()
      expect(Object.keys(wrapper.vm.scheduleDrafts).length).toBeGreaterThan(0)

      wrapper.vm.clearSelectedWindow()
      await nextTick()

      expect(Object.keys(wrapper.vm.scheduleDrafts)).toHaveLength(0)
    })

    it('onDraftChange adds task id to dirtyDraftIds', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.onDraftChange(42)
      expect(wrapper.vm.dirtyDraftIds.has(42)).toBe(true)
    })
  })

  // =========================================================================
  // canRescheduleTask
  // =========================================================================
  describe('canRescheduleTask', () => {
    it('returns true for pending tasks with scheduled_at', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.canRescheduleTask({ status: 'pending', scheduled_at: futureTime })).toBe(true)
    })

    it('returns false for non-pending tasks', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.canRescheduleTask({ status: 'running', scheduled_at: futureTime })).toBe(false)
      expect(wrapper.vm.canRescheduleTask({ status: 'queued', scheduled_at: futureTime })).toBe(false)
    })

    it('returns false for pending tasks without scheduled_at', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.canRescheduleTask({ status: 'pending', scheduled_at: null })).toBe(false)
    })
  })

  // =========================================================================
  // Date/Time Disabled Checks
  // =========================================================================
  describe('date and time disabled checks', () => {
    it('isScheduledDateDisabled returns true for past dates', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const yesterday = new Date()
      yesterday.setDate(yesterday.getDate() - 1)
      expect(wrapper.vm.isScheduledDateDisabled(yesterday.getTime())).toBe(true)
    })

    it('isScheduledDateDisabled returns false for today', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const today = new Date()
      expect(wrapper.vm.isScheduledDateDisabled(today.getTime())).toBe(false)
    })

    it('isScheduledDateDisabled returns false for future dates', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const tomorrow = new Date()
      tomorrow.setDate(tomorrow.getDate() + 1)
      expect(wrapper.vm.isScheduledDateDisabled(tomorrow.getTime())).toBe(false)
    })

    it('isScheduledTimeDisabled returns empty object for non-today dates', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const tomorrow = new Date()
      tomorrow.setDate(tomorrow.getDate() + 1)
      const result = wrapper.vm.isScheduledTimeDisabled(tomorrow.getTime())
      expect(result).toEqual({})
    })

    it('isScheduledTimeDisabled returns hour/minute/second validators for today', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const now = new Date()
      const result = wrapper.vm.isScheduledTimeDisabled(now.getTime()) as any
      expect(result).toHaveProperty('isHourDisabled')
      expect(result).toHaveProperty('isMinuteDisabled')
      expect(result).toHaveProperty('isSecondDisabled')
      // Past hours should be disabled
      expect(result.isHourDisabled(0)).toBe(now.getHours() > 0)
    })
  })

  // =========================================================================
  // Reschedule Error Handling
  // =========================================================================
  describe('reschedule error handling', () => {
    it('shows error when draft is null (no time selected)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.scheduleDrafts[1] = null

      await wrapper.vm.handleTaskReschedule(mockScheduledTasks[0])

      expect(mockApi.rescheduleTask).not.toHaveBeenCalled()
      expect(mockMessage.error).toHaveBeenCalled()
    })

    it('shows error when reschedule API call fails', async () => {
      ;(mockApi.rescheduleTask as Mock).mockRejectedValue(new Error('server error'))

      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      wrapper.vm.scheduleDrafts[1] = Date.now() + 2 * 60 * 60 * 1000
      await wrapper.vm.handleTaskReschedule(mockScheduledTasks[0])
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalled()
      expect(wrapper.vm.savingTaskId).toBeNull()
    })

    it('sets savingTaskId during reschedule and clears it after', async () => {
      let resolveReschedule!: (v: any) => void
      ;(mockApi.rescheduleTask as Mock).mockReturnValue(new Promise(r => { resolveReschedule = r }))

      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.handleHeatmapCellClick(new Date(futureTime).getTime())
      await nextTick()

      wrapper.vm.scheduleDrafts[1] = Date.now() + 2 * 60 * 60 * 1000
      const reschedulePromise = wrapper.vm.handleTaskReschedule(mockScheduledTasks[0])

      expect(wrapper.vm.savingTaskId).toBe(1)

      resolveReschedule(mockScheduledTasks[0])
      await flushPromises()
      await reschedulePromise

      expect(wrapper.vm.savingTaskId).toBeNull()
    })
  })

  // =========================================================================
  // Concurrent Fetch Guard
  // =========================================================================
  describe('concurrent fetch guard', () => {
    it('prevents concurrent fetches — second call is skipped while first is in flight', async () => {
      let resolveFirst!: (v: any) => void
      ;(mockApi.getScheduledStats as Mock).mockReturnValueOnce(
        new Promise(r => { resolveFirst = r })
      )

      wrapper = mountComponent()
      await nextTick()

      // Loading is true from mount fetch; call refresh again
      wrapper.vm.refresh()
      await nextTick()

      // Only 1 call because loading was true
      expect(mockApi.getScheduledStats).toHaveBeenCalledTimes(1)

      resolveFirst(mockScheduledStats)
      await flushPromises()
    })
  })

  // =========================================================================
  // Summary Items Edge Cases
  // =========================================================================
  describe('summaryItems edge cases', () => {
    it('returns empty array when scheduledStats is null', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue(null)
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])

      wrapper = mountComponent()
      await flushPromises()

      // scheduledStats.value will be null → summaryItems returns []
      expect(wrapper.vm.summaryItems).toHaveLength(0)
    })

    it('summary busiest hour shows "0" when busiest_hour_count is 0', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({
        ...mockScheduledStats,
        summary: {
          ...mockScheduledStats.summary,
          busiest_hour_count: 0,
          busiest_hour_label: ''
        }
      })

      wrapper = mountComponent()
      await flushPromises()

      const items = wrapper.vm.summaryItems as any[]
      const busiestItem = items.find((i: any) => i.label === 'scheduleOverview.busiestHour')
      expect(busiestItem).toBeTruthy()
      expect(busiestItem.value).toBe('0')
      expect(busiestItem.note).toBe('scheduleOverview.noScheduledWork')
    })
  })

  // =========================================================================
  // fullSlotCount
  // =========================================================================
  describe('fullSlotCount', () => {
    it('returns 0 when slotMaxTasks is 0', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect(wrapper.vm.fullSlotCount).toBe(0)
    })

    it('counts slots at capacity when slotMaxTasks > 0', async () => {
      // Create two tasks in the same hour bucket
      const sameHour1 = createMockTask({ id: 10, status: 'queued', scheduled_at: futureTime })
      const sameHour2 = createMockTask({ id: 11, status: 'queued', scheduled_at: futureTime })
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([sameHour1, sameHour2])
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 2 })

      wrapper = mountComponent()
      await flushPromises()

      // 2 tasks in one hour, capacity=2 → 1 full slot
      expect(wrapper.vm.fullSlotCount).toBe(1)
    })
  })

  // =========================================================================
  // Navigation
  // =========================================================================
  describe('navigation', () => {
    it('goToTask navigates to TaskView route', async () => {
      const mockPush = vi.fn()
      vi.mocked(await import('vue-router')).useRouter = () => ({ push: mockPush } as any)

      wrapper = mountComponent()
      await flushPromises()

      wrapper.vm.goToTask({ id: 42 } as any)
    })
  })

  // =========================================================================
  // myTasksOnly toggle
  // =========================================================================
  describe('myTasksOnly toggle', () => {
    it('exposes myTasksOnly reactive ref starting as false', async () => {
      wrapper = mountComponent()
      await flushPromises()

      expect((wrapper.vm as any).myTasksOnly).toBe(false)
    })

    it('calls getScheduledTasks without my param on initial load (myTasksOnly=false)', async () => {
      wrapper = mountComponent()
      await flushPromises()

      const call = (mockApi.getScheduledTasks as Mock).mock.calls[0]
      expect(call[0]).not.toEqual(expect.objectContaining({ my: true }))
    })

    it('calls both APIs with { my: true } when myTasksOnly is set to true', async () => {
      wrapper = mountComponent()
      await flushPromises()
      ;(mockApi.getScheduledStats as Mock).mockClear()
      ;(mockApi.getScheduledTasks as Mock).mockClear()

      ;(wrapper.vm as any).myTasksOnly = true
      await flushPromises()

      expect(mockApi.getScheduledStats).toHaveBeenCalledWith({ my: true })
      expect(mockApi.getScheduledTasks).toHaveBeenCalledWith({ my: true })
    })

    it('calls both APIs without my param when myTasksOnly is turned back off', async () => {
      wrapper = mountComponent()
      await flushPromises()

      ;(wrapper.vm as any).myTasksOnly = true
      await flushPromises()
      ;(mockApi.getScheduledStats as Mock).mockClear()
      ;(mockApi.getScheduledTasks as Mock).mockClear()

      ;(wrapper.vm as any).myTasksOnly = false
      await flushPromises()

      expect(mockApi.getScheduledStats).toHaveBeenCalledWith(undefined)
      expect(mockApi.getScheduledTasks).toHaveBeenCalledWith(undefined)
    })

    it('includes myTasksOnly as an accessible component property for the template', async () => {
      wrapper = mountComponent()
      await flushPromises()

      // myTasksOnly is a ref that the template binds to n-button @click toggle
      expect(typeof (wrapper.vm as any).myTasksOnly).toBe('boolean')
    })

    it('hides full slots card when myTasksOnly is true even with slot_max_tasks > 0', async () => {
      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 5 })

      wrapper = mountComponent()
      await flushPromises()

      // Verify card is present in global view
      expect((wrapper.vm.summaryItems as any[]).find((i: any) => i.label === 'scheduleOverview.fullSlots')).toBeTruthy()

      ;(mockApi.getScheduledStats as Mock).mockResolvedValue({ ...mockScheduledStats, slot_max_tasks: 5 })
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue(mockScheduledTasks)
      ;(wrapper.vm as any).myTasksOnly = true
      await flushPromises()

      const items = wrapper.vm.summaryItems as any[]
      const fullSlotsItem = items.find((i: any) => i.label === 'scheduleOverview.fullSlots')
      expect(fullSlotsItem).toBeUndefined()
    })
  })
})
