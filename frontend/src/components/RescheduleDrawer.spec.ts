import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import RescheduleDrawer from './RescheduleDrawer.vue'

const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    rescheduleTask: vi.fn<() => Promise<any>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getConfig: vi.fn<() => Promise<any>>(),
    getTaskScheduleConstraints: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

vi.mock('../api', () => ({
  rescheduleTask: mockApi.rescheduleTask,
  getScheduledTasks: mockApi.getScheduledTasks,
  getConfig: mockApi.getConfig,
  getTaskScheduleConstraints: mockApi.getTaskScheduleConstraints,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
  }),
}))

vi.mock('../utils/datetime', () => ({
  parseUtcDate: vi.fn((value: string) => new Date(value)),
}))

vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((error: any, t: any, fallbackKey: string) => {
    const detail = error?.response?.data?.detail
    return typeof detail === 'string' ? detail : t(fallbackKey)
  }),
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
  }),
}))

vi.mock('./HeatmapChart.vue', () => ({
  default: {
    name: 'HeatmapChart',
    props: ['tasks', 'selectedMs', 'maxPerSlot', 'enforceCapacity'],
    emits: ['cell-click'],
    setup(_props: any, { emit }: any) {
      return () => h('button', {
        class: 'heatmap-chart-mock',
        onClick: () => emit('cell-click', Date.now() + 3600000),
      })
    },
  },
}))

vi.mock('naive-ui', () => ({
  NDrawer: {
    name: 'NDrawer',
    props: ['show', 'width', 'placement'],
    setup(props: any, { attrs, slots }: any) {
      return () => props.show
        ? h('div', { ...attrs, class: ['n-drawer', attrs.class] }, slots.default?.())
        : null
    },
  },
  NDrawerContent: {
    name: 'NDrawerContent',
    props: ['title', 'closable'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-drawer-content' }, [
        slots.default?.(),
        slots.footer?.(),
      ])
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled'],
    setup(props: any, { attrs, slots }: any) {
      return () => h('button', {
        ...attrs,
        class: ['n-button', attrs.class],
        disabled: props.disabled || props.loading,
      }, slots.default?.())
    },
  },
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => props.show
        ? h('div', { class: 'n-spin-loading' }, props.description)
        : h('div', { class: 'n-spin' }, slots.default?.())
    },
  },
  NForm: {
    name: 'NForm',
    props: ['label-placement'],
    setup(_props: any, { slots }: any) {
      return () => h('form', {}, slots.default?.())
    },
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, slots.default?.())
    },
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'clearable', 'isDateDisabled', 'isTimeDisabled'],
    setup(props: any) {
      return () => h('div', {
        class: 'n-date-picker',
        'data-value': props.value,
        'data-has-time-disabled': typeof props.isTimeDisabled === 'function',
      })
    },
  },
  NTooltip: {
    name: 'NTooltip',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tooltip' }, [
        slots.trigger?.(),
        slots.default?.(),
      ])
    },
  },
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    setup() {
      return () => h('i', { class: 'n-icon' })
    },
  },
  useMessage: () => mockMessage,
}))

vi.mock('./task-process/taskProcessUtils', () => ({
  renderMarkdown: vi.fn((value: string) => `<p>${value}</p>`),
}))

function createTask(overrides: Record<string, any> = {}) {
  return {
    id: 8,
    user_prompt: 'Scheduled task',
    status: 'pending',
    scheduled_at: '2026-04-01T10:00:00Z',
    created_at: '2026-03-31T10:00:00Z',
    updated_at: '2026-03-31T10:00:00Z',
    ...overrides,
  }
}

describe('RescheduleDrawer', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    resetMockApi()
    Object.values(mockMessage).forEach(fn => fn.mockReset())
    mockApi.getScheduledTasks.mockResolvedValue([{ id: 31 }])
    mockApi.getConfig.mockResolvedValue({
      runtime: { slot_max_tasks: 3, slot_max_tasks_enforce: true },
    })
    mockApi.rescheduleTask.mockResolvedValue(createTask())
    mockApi.getTaskScheduleConstraints.mockResolvedValue(null)
  })

  afterEach(() => {
    wrapper?.unmount()
  })

  async function mountDrawer(props: Record<string, any> = {}) {
    wrapper = mount(RescheduleDrawer, {
      props: {
        show: false,
        task: createTask(),
        ...props,
      },
    })
    await flushPromises()
    return wrapper
  }

  async function openDrawer() {
    await wrapper.setProps({ show: true })
    await flushPromises()
    await nextTick()
  }

  it('preloads the task scheduled time and schedule preview when opened', async () => {
    await mountDrawer({ task: createTask({ scheduled_at: '2026-04-01T10:00:00Z' }) })

    await openDrawer()

    expect(wrapper.vm.scheduleDatetime).toBe(new Date('2026-04-01T10:00:00Z').getTime())
    expect(mockApi.getScheduledTasks).toHaveBeenCalled()
    expect(wrapper.vm.scheduledTasks).toEqual([{ id: 31 }])
    expect(wrapper.vm.slotMaxTasks).toBe(3)
    expect(wrapper.vm.slotEnforce).toBe(true)
  })

  it('passes a time-disabled predicate when schedule constraints are loaded', async () => {
    mockApi.getTaskScheduleConstraints.mockResolvedValue({
      has_valid_window: true,
      min_scheduled_at: '2026-04-01T10:00:00Z',
      max_scheduled_at: '2026-04-02T18:00:00Z',
      min_source_task_id: 1,
      max_source_task_id: 2,
    })
    await mountDrawer()
    await openDrawer()

    const picker = wrapper.find('.n-date-picker')
    expect(picker.attributes('data-has-time-disabled')).toBe('true')
    expect(typeof wrapper.vm.isTimeDisabled).toBe('function')
    // On the min boundary day the hour before the floor is disabled.
    const min = new Date('2026-04-01T10:00:00Z')
    const validator = wrapper.vm.isTimeDisabled(min.getTime())
    expect(validator.isHourDisabled?.(min.getHours() - 1)).toBe(true)
    expect(validator.isHourDisabled?.(min.getHours() + 1)).toBe(false)
  })

  it('sets selected time to null when the task has no scheduled_at', async () => {
    await mountDrawer({ task: createTask({ scheduled_at: null }) })

    await openDrawer()

    expect(wrapper.vm.scheduleDatetime).toBeNull()
  })

  it('uses heatmap clicks as the selected schedule time', async () => {
    await mountDrawer()
    await openDrawer()
    const selectedTime = Date.now() + 3600000

    wrapper.vm.handleHeatmapCellClick(selectedTime)

    expect(wrapper.vm.scheduleDatetime).toBe(selectedTime)
  })

  it('warns when submitting without a selected time', async () => {
    await mountDrawer({ task: createTask({ scheduled_at: null }) })
    await openDrawer()
    wrapper.vm.scheduleDatetime = null

    await wrapper.vm.handleSubmit()

    expect(mockMessage.warning).toHaveBeenCalledWith('taskView.selectRescheduleTime')
    expect(mockApi.rescheduleTask).not.toHaveBeenCalled()
  })

  it('warns when submitting a past time', async () => {
    await mountDrawer()
    await openDrawer()
    wrapper.vm.scheduleDatetime = Date.now() - 1000

    await wrapper.vm.handleSubmit()

    expect(mockMessage.warning).toHaveBeenCalledWith('taskView.rescheduleTimeFuture')
    expect(mockApi.rescheduleTask).not.toHaveBeenCalled()
  })

  it('submits future schedule time and emits the updated task', async () => {
    const updatedTask = createTask({ scheduled_at: '2026-04-02T10:00:00Z' })
    mockApi.rescheduleTask.mockResolvedValue(updatedTask)
    await mountDrawer()
    await openDrawer()
    const futureMs = Date.now() + 3600000

    wrapper.vm.scheduleDatetime = futureMs
    await wrapper.vm.handleSubmit()
    await flushPromises()

    expect(mockApi.rescheduleTask).toHaveBeenCalledWith(8, {
      scheduled_datetime: new Date(futureMs).toISOString(),
    })
    expect(mockMessage.success).toHaveBeenCalledWith('taskView.taskRescheduled')
    expect(wrapper.emitted('rescheduled')?.[0]).toEqual([updatedTask])
    expect(wrapper.emitted('update:show')?.[0]).toEqual([false])
  })

  it('shows extracted slot errors and resets loading when submit fails', async () => {
    mockApi.rescheduleTask.mockRejectedValue({
      response: { data: { detail: 'Slot is full' } },
    })
    await mountDrawer()
    await openDrawer()

    wrapper.vm.scheduleDatetime = Date.now() + 3600000
    await wrapper.vm.handleSubmit()
    await flushPromises()

    expect(mockMessage.error).toHaveBeenCalledWith('Slot is full')
    expect(wrapper.vm.loading).toBe(false)
  })

  it('falls back to an empty preview when scheduled tasks fail to load', async () => {
    mockApi.getScheduledTasks.mockRejectedValue(new Error('API Error'))
    await mountDrawer()

    await openDrawer()

    expect(wrapper.vm.scheduledTasks).toEqual([])
  })
})
