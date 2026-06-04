import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import TaskFormDrawer from './TaskFormDrawer.vue'

const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    createTask: vi.fn<() => Promise<any>>(),
    updateTask: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
    getProviders: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>(),
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg }
})

vi.mock('../i18n', () => ({ currentLocale: ref('en') }))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((value: any) => `formatted-${value}`),
  formatTimeUtc8: vi.fn((value: any) => `time-${value}`),
}))

vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((error: any, t: any, fallbackKey: string) => {
    const detail = error?.response?.data?.detail
    return typeof detail === 'string' ? detail : t(fallbackKey)
  }),
}))

vi.mock('../utils/usageLimits', () => ({
  formatUsageResetAt: vi.fn((value: string) => `reset-${value}`),
  isUsageLimitExceededDetail: vi.fn((detail: any) => detail?.reason === 'usage_limit_exceeded'),
}))

vi.mock('../api', () => ({
  createTask: mockApi.createTask,
  updateTask: mockApi.updateTask,
  getPromptTemplates: mockApi.getPromptTemplates,
  getProviders: mockApi.getProviders,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
  getConfig: mockApi.getConfig,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
  }),
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
    isCompact: ref(false),
    width: ref(1200),
  }),
}))

vi.mock('naive-ui', () => ({
  NAlert: {
    name: 'NAlert',
    props: ['type'],
    setup(_props: any, { attrs, slots }: any) {
      return () => h('div', { ...attrs, class: ['n-alert', attrs.class] }, slots.default?.())
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'secondary', 'strong', 'round', 'loading', 'disabled', 'size', 'ghost', 'quaternary', 'circle'],
    setup(props: any, { attrs, slots }: any) {
      return () => h('button', {
        ...attrs,
        class: ['n-button', attrs.class, { loading: props.loading, disabled: props.disabled }],
        disabled: props.disabled || props.loading,
      }, [slots.icon?.(), slots.default?.()])
    },
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'clearable', 'isDateDisabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-date-picker',
        value: props.value ?? '',
        onInput: (event: Event) => emit('update:value', Number((event.target as HTMLInputElement).value)),
      })
    },
  },
  NDrawer: {
    name: 'NDrawer',
    props: ['show', 'width', 'placement'],
    setup(props: any, { attrs, slots }: any) {
      return () => props.show ? h('div', { ...attrs, class: ['n-drawer', attrs.class] }, slots.default?.()) : null
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
  NForm: {
    name: 'NForm',
    props: ['labelPlacement'],
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
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    setup() {
      return () => h('i', { class: 'n-icon' })
    },
  },
  NRadio: {
    name: 'NRadio',
    props: ['value'],
    setup(props: any, { slots }: any) {
      return () => h('label', { class: 'n-radio', 'data-value': props.value }, slots.default?.())
    },
  },
  NRadioGroup: {
    name: 'NRadioGroup',
    props: ['value'],
    emits: ['update:value'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-radio-group' }, slots.default?.())
    },
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'clearable', 'placeholder'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        value: props.value ?? '',
        onChange: (event: Event) => emit('update:value', Number((event.target as HTMLSelectElement).value) || null),
      }, props.options?.map((option: any) => h('option', { value: option.value }, option.label)))
    },
  },
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin-loading' : 'n-spin' }, slots.default?.())
    },
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value', 'size'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        onClick: () => emit('update:value', !props.value),
      })
    },
  },
  NTooltip: {
    name: 'NTooltip',
    props: ['trigger', 'placement'],
    setup(_props: any, { slots }: any) {
      return () => h('span', { class: 'n-tooltip' }, [slots.trigger?.(), slots.default?.()])
    },
  },
  useMessage: () => mockMessage,
}))

vi.mock('@vicons/ionicons5', () => {
  const icon = (name: string) => ({ name, render: () => null })
  return {
    BulbOutline: icon('BulbOutline'),
    CalendarOutline: icon('CalendarOutline'),
    CloseOutline: icon('CloseOutline'),
    CodeSlashOutline: icon('CodeSlashOutline'),
    DocumentTextOutline: icon('DocumentTextOutline'),
    InformationCircleOutline: icon('InformationCircleOutline'),
    WarningOutline: icon('WarningOutline'),
  }
})

vi.mock('./VariableEditor.vue', () => ({
  default: {
    name: 'VariableEditor',
    props: ['modelValue', 'variableTips', 'placeholder'],
    emits: ['update:modelValue'],
    setup(props: any, { emit }: any) {
      return () => h('textarea', {
        class: 'variable-editor-mock',
        value: props.modelValue,
        placeholder: props.placeholder,
        onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLTextAreaElement).value),
      })
    },
  },
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

const mockTemplates = [
  { id: 1, name: 'Bug Fix', content: 'Fix {{issue_type}}', variable_tips: { issue_type: 'Bug type' } },
  { id: 2, name: 'Simple', content: 'Do something' },
]

const mockProviders = [
  { id: 7, name: 'Default Provider', model: 'model-a', is_default: true },
]

describe('TaskFormDrawer', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.useRealTimers()
    resetMockApi()
    Object.values(mockMessage).forEach(fn => fn.mockReset())
    mockApi.getPromptTemplates.mockResolvedValue(mockTemplates)
    mockApi.getProviders.mockResolvedValue(mockProviders)
    mockApi.getScheduledTasks.mockResolvedValue([])
    mockApi.getSlotCapacity.mockResolvedValue(null)
    mockApi.getConfig.mockResolvedValue({ runtime: { slot_max_tasks: 5, slot_max_tasks_enforce: false } })
    mockApi.createTask.mockResolvedValue({ id: 10 })
    mockApi.updateTask.mockResolvedValue({ id: 10 })
  })

  afterEach(() => {
    wrapper?.unmount()
    vi.useRealTimers()
  })

  async function mountDrawer(props: Record<string, any> = {}) {
    wrapper = mount(TaskFormDrawer, {
      props: {
        show: false,
        mode: 'create',
        issueId: 1,
        issueDescription: 'Issue description',
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

  async function submitCreate() {
    await wrapper.find('[data-testid="issue-create-task-button"]').trigger('click')
    await flushPromises()
  }

  describe('create mode', () => {
    it('pre-fills prompt from issue description when opened', async () => {
      await mountDrawer({ issueDescription: 'Auto-filled description' })
      await openDrawer()

      expect((wrapper.find('.variable-editor-mock').element as HTMLTextAreaElement).value).toBe('Auto-filled description')
    })

    it('does not overwrite an existing prompt when reopened', async () => {
      await mountDrawer({ issueDescription: 'Issue desc' })
      await openDrawer()

      await wrapper.find('.variable-editor-mock').setValue('Existing prompt')
      await wrapper.setProps({ show: false })
      await wrapper.setProps({ show: true })
      await nextTick()

      expect((wrapper.find('.variable-editor-mock').element as HTMLTextAreaElement).value).toBe('Existing prompt')
    })

    it('warns when scheduled mode has no selected time', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledAt = null
      await submitCreate()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.pleaseSelectScheduledTime')
      expect(mockApi.createTask).not.toHaveBeenCalled()
    })

    it('warns when scheduled time is in the past', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledAt = Date.now() - 60000
      await submitCreate()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.scheduledTimeFuture')
      expect(mockApi.createTask).not.toHaveBeenCalled()
    })

    it('sends scheduled_datetime for future scheduled tasks', async () => {
      await mountDrawer()
      await openDrawer()
      const futureMs = Date.now() + 3600000

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledAt = futureMs
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          issue_id: 1,
          scheduled_datetime: new Date(futureMs).toISOString(),
        }),
      )
      expect(mockMessage.success).toHaveBeenCalledWith('issue.taskCreated')
    })

    it('does not include scheduled_datetime when schedule type is now', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.scheduleType = 'now'
      wrapper.vm.scheduledAt = null
      await submitCreate()

      expect(mockApi.createTask.mock.calls[0][0].scheduled_datetime).toBeUndefined()
    })

    it('resets create state and emits close after successful creation', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledAt = Date.now() + 3600000
      wrapper.vm.prompt = 'test prompt'
      await submitCreate()

      expect(wrapper.vm.prompt).toBe('')
      expect(wrapper.vm.scheduledAt).toBeNull()
      expect(wrapper.vm.scheduleType).toBe('now')
      expect(wrapper.emitted('update:show')?.at(-1)).toEqual([false])
      expect(wrapper.emitted('created')?.[0]).toEqual([{ id: 10 }])
    })

    it('trims and includes a non-empty user prompt', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.prompt = '  Custom prompt text  '
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          user_prompt: 'Custom prompt text',
        }),
      )
    })

    it('shows a usage limit alert without a generic error toast', async () => {
      mockApi.createTask.mockRejectedValue({
        response: {
          data: {
            detail: {
              reason: 'usage_limit_exceeded',
              scope: 'user',
              exceeded_items: [
                {
                  field: 'daily_tasks',
                  window: 'daily',
                  metric: 'tasks',
                  used: 6,
                  limit: 5,
                  reset_at: '2026-04-29T00:00:00+08:00',
                },
              ],
            },
          },
        },
      })
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      const quotaAlert = wrapper.find('[data-testid="issue-create-task-usage-alert"]')
      expect(quotaAlert.exists()).toBe(true)
      expect(quotaAlert.text()).toContain('6/5')
      expect(quotaAlert.text()).toContain('reset-2026-04-29T00:00:00+08:00')
      expect(mockMessage.error).not.toHaveBeenCalled()
    })
  })

  describe('template handling', () => {
    it('applies template content and variable tips', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.applyPromptTemplate(mockTemplates[0])

      expect(wrapper.vm.prompt).toBe('Fix {{issue_type}}')
      expect(wrapper.vm.promptVariableTips).toEqual({ issue_type: 'Bug type' })
    })

    it('keeps existing variable tips when a template has no tips', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.promptVariableTips = { old: 'tip' }
      wrapper.vm.applyPromptTemplate(mockTemplates[1])

      expect(wrapper.vm.prompt).toBe('Do something')
      expect(wrapper.vm.promptVariableTips).toEqual({ old: 'tip' })
    })

    it('applies a template immediately when prompt is empty', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.prompt = ''
      wrapper.vm.handleTemplateItemClick(mockTemplates[1])

      expect(wrapper.vm.prompt).toBe('Do something')
      expect(wrapper.vm.showTemplateDrawer).toBe(false)
      expect(wrapper.vm.pendingTemplate).toBeNull()
    })

    it('shows inline overwrite confirmation when prompt has content', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.prompt = 'Existing prompt'
      wrapper.vm.showTemplateDrawer = true
      wrapper.vm.handleTemplateItemClick(mockTemplates[1])
      await nextTick()

      expect(wrapper.vm.prompt).toBe('Existing prompt')
      expect(wrapper.vm.pendingTemplate).toEqual(mockTemplates[1])
      expect(wrapper.find('.template-overwrite-banner').exists()).toBe(true)
    })

    it('confirmation applies the pending template and closes the drawer', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.prompt = 'Old content'
      wrapper.vm.showTemplateDrawer = true
      wrapper.vm.handleTemplateItemClick(mockTemplates[0])
      wrapper.vm.confirmTemplateOverwrite()

      expect(wrapper.vm.prompt).toBe('Fix {{issue_type}}')
      expect(wrapper.vm.promptVariableTips).toEqual({ issue_type: 'Bug type' })
      expect(wrapper.vm.pendingTemplate).toBeNull()
      expect(wrapper.vm.showTemplateDrawer).toBe(false)
    })
  })

  describe('schedule context and slot capacity', () => {
    it('opens heatmap drawer and loads scheduled tasks', async () => {
      mockApi.getScheduledTasks.mockResolvedValue([{ id: 1 }])
      await mountDrawer()
      await openDrawer()
      wrapper.vm.scheduledTasksForPreview = []
      mockApi.getScheduledTasks.mockClear()

      await wrapper.vm.openHeatmapDrawer()
      await flushPromises()

      expect(wrapper.vm.showHeatmapDrawer).toBe(true)
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
      expect(mockApi.getConfig).toHaveBeenCalled()
    })

    it('handles scheduled task loading errors', async () => {
      mockApi.getScheduledTasks.mockRejectedValue(new Error('fail'))
      await mountDrawer()
      await openDrawer()

      await wrapper.vm.openHeatmapDrawer()
      await flushPromises()

      expect(wrapper.vm.showHeatmapDrawer).toBe(true)
      expect(wrapper.vm.scheduledTasksForPreview).toEqual([])
    })

    it('does not re-fetch scheduled tasks when preview data is already loaded', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.scheduledTasksForPreview = [{ id: 1 }]
      mockApi.getScheduledTasks.mockClear()
      await wrapper.vm.openHeatmapDrawer()
      await flushPromises()

      expect(mockApi.getScheduledTasks).not.toHaveBeenCalled()
    })

    it('sets slot limits from config', async () => {
      mockApi.getConfig.mockResolvedValue({
        runtime: { slot_max_tasks: 10, slot_max_tasks_enforce: true },
      })
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.slotMaxTasks).toBe(10)
      expect(wrapper.vm.slotEnforce).toBe(true)
    })

    it('keeps the heatmap drawer open when config loading fails', async () => {
      mockApi.getConfig.mockRejectedValue(new Error('config fail'))
      await mountDrawer()
      await openDrawer()

      await wrapper.vm.openHeatmapDrawer()
      await flushPromises()

      expect(wrapper.vm.showHeatmapDrawer).toBe(true)
    })

    it('selecting a heatmap cell sets schedule time and closes the drawer', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.showHeatmapDrawer = true
      const ts = Date.now() + 3600000
      wrapper.vm.handleHeatmapCellClick(ts)

      expect(wrapper.vm.scheduledAt).toBe(ts)
      expect(wrapper.vm.showHeatmapDrawer).toBe(false)
    })

    it('clears schedule time when schedule type changes to now', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.scheduledAt = Date.now() + 3600000
      wrapper.vm.scheduleType = 'scheduled'
      await nextTick()
      wrapper.vm.scheduleType = 'now'
      await nextTick()

      expect(wrapper.vm.scheduledAt).toBeNull()
    })

    it('checks slot capacity after debounce', async () => {
      await mountDrawer()
      await openDrawer()
      vi.useFakeTimers()
      mockApi.getSlotCapacity.mockResolvedValue({ available: 3 })

      wrapper.vm.scheduledAt = Date.now() + 3600000
      await nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()

      expect(mockApi.getSlotCapacity).toHaveBeenCalled()
      expect(wrapper.vm.slotCapacity).toEqual({ available: 3 })
    })

    it('clears slot capacity when schedule time is cleared', async () => {
      await mountDrawer()
      await openDrawer()
      vi.useFakeTimers()
      mockApi.getSlotCapacity.mockResolvedValue({ available: 5 })

      wrapper.vm.scheduledAt = Date.now() + 3600000
      await nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      expect(wrapper.vm.slotCapacity).toEqual({ available: 5 })

      wrapper.vm.scheduledAt = null
      await nextTick()

      expect(wrapper.vm.slotCapacity).toBeNull()
    })

    it('handles slot capacity API errors gracefully', async () => {
      await mountDrawer()
      await openDrawer()
      vi.useFakeTimers()
      mockApi.getSlotCapacity.mockRejectedValue(new Error('fail'))

      wrapper.vm.scheduledAt = Date.now() + 3600000
      await nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()

      expect(wrapper.vm.slotCapacity).toBeNull()
      expect(wrapper.vm.slotCapacityLoading).toBe(false)
    })
  })

  describe('edit mode', () => {
    const existingTask = {
      id: 42,
      user_prompt: 'Original prompt',
      priority: 1,
      require_changes: true,
      provider_id: 7,
    }

    async function mountEditDrawer(taskOverrides: Record<string, any> = {}) {
      wrapper = mount(TaskFormDrawer, {
        props: {
          show: false,
          mode: 'edit',
          task: { ...existingTask, ...taskOverrides },
        },
      })
      await flushPromises()
      return wrapper
    }

    it('pre-fills form from task when drawer opens', async () => {
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.prompt).toBe('Original prompt')
      expect(wrapper.vm.priority).toBe(1)
      expect(wrapper.vm.requireChanges).toBe(true)
      expect(wrapper.vm.selectedProviderId).toBe(7)
    })

    it('re-populates form from updated task on each open', async () => {
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      await wrapper.setProps({ show: false })
      await wrapper.setProps({ task: { ...existingTask, user_prompt: 'Updated prompt', provider_id: null } })
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.prompt).toBe('Updated prompt')
      expect(wrapper.vm.selectedProviderId).toBeNull()
    })

    it('calls updateTask with only changed fields', async () => {
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      wrapper.vm.prompt = 'New prompt'
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockApi.updateTask).toHaveBeenCalledWith(42, { user_prompt: 'New prompt' })
    })

    it('sends no request and closes when nothing changed', async () => {
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockApi.updateTask).not.toHaveBeenCalled()
      expect(wrapper.emitted('update:show')?.at(-1)).toEqual([false])
    })

    it('emits updated event with server response on success', async () => {
      const updatedTask = { ...existingTask, user_prompt: 'New prompt' }
      mockApi.updateTask.mockResolvedValue(updatedTask)
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      wrapper.vm.prompt = 'New prompt'
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(wrapper.emitted('updated')?.[0]).toEqual([updatedTask])
      expect(wrapper.emitted('update:show')?.at(-1)).toEqual([false])
      expect(mockMessage.success).toHaveBeenCalledWith('taskView.taskUpdated')
    })

    it('warns and does not call API when prompt is cleared', async () => {
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      wrapper.vm.prompt = '   '
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.pleaseEnterPrompt')
      expect(mockApi.updateTask).not.toHaveBeenCalled()
    })

    it('shows string detail from 409 response as error toast', async () => {
      mockApi.updateTask.mockRejectedValue({
        response: { data: { detail: 'Task is already running' } },
      })
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      wrapper.vm.prompt = 'Changed'
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('Task is already running')
    })

    it('shows generic fallback toast on non-string error detail', async () => {
      mockApi.updateTask.mockRejectedValue({ response: { data: {} } })
      await mountEditDrawer()
      await wrapper.setProps({ show: true })
      await flushPromises()

      wrapper.vm.priority = 0
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('taskView.failedToUpdateTask')
    })
  })
})
