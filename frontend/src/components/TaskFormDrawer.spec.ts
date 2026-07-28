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
    getWorkerProfiles: vi.fn<() => Promise<any[]>>(),
    getSkills: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>(),
    getRunInstructionTemplateDefaults: vi.fn<() => Promise<any>>(),
    previewRunInstructionTemplate: vi.fn<() => Promise<any>>(),
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
  getWorkerProfiles: mockApi.getWorkerProfiles,
  getSkills: mockApi.getSkills,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
  getConfig: mockApi.getConfig,
  getRunInstructionTemplateDefaults: mockApi.getRunInstructionTemplateDefaults,
  previewRunInstructionTemplate: mockApi.previewRunInstructionTemplate,
}))

vi.mock('./RunInstructionTemplateEditor.vue', () => ({
  default: {
    name: 'RunInstructionTemplateEditor',
    props: {
      modelValue: String,
      availablePlaceholders: Array,
      previewResult: String,
      previewError: String,
      embedded: Boolean,
    },
    emits: ['update:modelValue', 'restore-default', 'preview'],
    setup(props: any, { emit }: any) {
      return () => h('div', { class: 'run-instruction-editor-mock' }, [
        h('textarea', {
          value: props.modelValue,
          onInput: (event: Event) => emit('update:modelValue', (event.target as HTMLTextAreaElement).value)
        }),
        h('button', { class: 'restore-run-instruction', onClick: () => emit('restore-default') }, 'restore'),
        h('button', { class: 'preview-run-instruction', onClick: () => emit('preview') }, 'preview'),
        props.previewResult ? h('pre', props.previewResult) : null,
        props.previewError ? h('span', props.previewError) : null
      ])
    }
  }
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
    props: ['title', 'closable', 'nativeScrollbar'],
    setup(props: any, { slots }: any) {
      return () => h('div', {
        class: 'n-drawer-content',
        'data-native-scrollbar': String(props.nativeScrollbar)
      }, [
        slots.default?.(),
        slots.footer?.(),
      ])
    },
  },
  NScrollbar: {
    name: 'NScrollbar',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-scrollbar' }, slots.default?.())
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
    props: ['label', 'validationStatus', 'feedback'],
    setup(props: any, { attrs, slots }: any) {
      return () => h('div', {
        ...attrs,
        class: ['n-form-item', attrs.class, props.validationStatus ? `n-form-item--${props.validationStatus}` : null],
      }, [
        slots.label ? h('div', { class: 'n-form-item-label' }, slots.label()) : null,
        slots.default?.(),
        props.feedback ? h('div', { class: 'n-form-item-feedback' }, props.feedback) : null,
      ])
    },
  },
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    setup(_props: any, { attrs }: any) {
      return () => h('i', { ...attrs, class: ['n-icon', attrs.class] })
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
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        value: props.value ?? '',
        disabled: props.disabled,
        onInput: (event: Event) => {
          emit('update:value', (event.target as HTMLInputElement).value)
        },
      })
    },
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'clearable', 'placeholder', 'multiple', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        multiple: props.multiple,
        disabled: props.disabled,
        value: props.value ?? '',
        onChange: (event: Event) => {
          const select = event.target as HTMLSelectElement
          emit('update:value', props.multiple
            ? Array.from(select.selectedOptions).map(option => option.value)
            : Number(select.value) || null)
        },
      }, props.options?.map((option: any) => h('option', { value: option.value, disabled: option.disabled }, option.label)))
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
    props: ['value', 'size', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { attrs, emit }: any) {
      return () => h('button', {
        ...attrs,
        class: 'n-switch',
        disabled: props.disabled,
        onClick: () => {
          if (!props.disabled) emit('update:value', !props.value)
        },
      })
    },
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_props: any, { slots }: any) {
      return () => h('span', { class: 'n-tag' }, slots.default?.())
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
    CheckmarkCircleOutline: icon('CheckmarkCircleOutline'),
    DocumentTextOutline: icon('DocumentTextOutline'),
    InformationCircleOutline: icon('InformationCircleOutline'),
    FlashOutline: icon('FlashOutline'),
    TimeOutline: icon('TimeOutline'),
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
  { id: 1, name: 'Bug Fix', content: 'Fix {{issue_type}}', variable_tips: { issue_type: 'Bug type' }, tags: ['backend', 'review'], is_active: true, sort_order: 1, created_at: '2026-03-31T10:00:00Z', updated_at: '2026-03-31T10:00:00Z' },
  { id: 2, name: 'Simple', content: 'Do something', tags: ['frontend'], is_active: true, sort_order: 2, created_at: '2026-03-30T10:00:00Z', updated_at: '2026-03-30T10:00:00Z' },
]

const mockProviders = [
  { id: 7, name: 'Default Provider', model: 'model-a', is_default: true, is_disabled: false },
]

const mockWorkerProfiles = [
  {
    id: 3,
    name: 'Java Worker',
    description: null,
    enabled: true,
    is_default: true,
    image: 'worker-java:latest',
    runtime_mode: 'mounted_kit',
    worker_kit_version: '0.3.5',
    worker_kit_path: '/opt/codify/worker-kits/0.3.5-linux-amd64',
    codegraph_enabled: false,
    volume_mounts: [],
    environment_variables: [],
    default_skill_ids: [11],
    pre_script: '',
    post_script: '',
    default_execute_run_instruction_template: 'Worker execute {{user_prompt}}',
    default_plan_run_instruction_template: 'Worker plan {{user_prompt}}',
    ci_auto_repair_run_instruction_template: 'Worker repair {{issue_title}}',
    created_at: '',
    updated_at: ''
  },
  {
    id: 4,
    name: 'Python Worker',
    description: null,
    enabled: true,
    is_default: false,
    image: 'worker-python:latest',
    runtime_mode: 'baked_image',
    worker_kit_version: null,
    worker_kit_path: null,
    codegraph_enabled: false,
    volume_mounts: [],
    environment_variables: [],
    default_skill_ids: [],
    pre_script: '',
    post_script: '',
    default_execute_run_instruction_template: 'Python execute {{user_prompt}}',
    default_plan_run_instruction_template: 'Python plan {{user_prompt}}',
    ci_auto_repair_run_instruction_template: 'Python repair {{issue_title}}',
    created_at: '',
    updated_at: ''
  }
]

describe('TaskFormDrawer', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.useRealTimers()
    resetMockApi()
    Object.values(mockMessage).forEach(fn => fn.mockReset())
    mockApi.getPromptTemplates.mockResolvedValue(mockTemplates)
    mockApi.getProviders.mockResolvedValue(mockProviders)
    mockApi.getWorkerProfiles.mockResolvedValue(mockWorkerProfiles)
    mockApi.getSkills.mockResolvedValue([
      { id: 11, name: 'review', description: 'Review changes', version_id: 101 }
    ])
    mockApi.getScheduledTasks.mockResolvedValue([])
    mockApi.getSlotCapacity.mockResolvedValue(null)
    mockApi.getConfig.mockResolvedValue({ runtime: { slot_max_tasks: 5, slot_max_tasks_enforce: false } })
    mockApi.getRunInstructionTemplateDefaults.mockResolvedValue({
      execute: { content: 'Execute {{user_prompt}}', available_placeholders: ['user_prompt'] },
      plan: { content: 'Plan {{user_prompt}}', available_placeholders: ['user_prompt'] }
    })
    mockApi.previewRunInstructionTemplate.mockResolvedValue({
      rendered_prompt: 'Rendered prompt',
      used_placeholders: ['user_prompt'],
      unused_known_placeholders: []
    })
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
        workerProfileId: 3,
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
    it('inherits skills for a capable mounted-kit profile without sending an override', async () => {
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.taskSkillSelectionSupported).toBe(true)
      expect(wrapper.vm.inheritProfileSkills).toBe(true)
      expect(wrapper.vm.selectedSkillIds).toEqual([11])
      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.not.objectContaining({ skill_ids: expect.anything() })
      )
    })

    it('excludes retained disabled Profile Skills when creating an explicit override', async () => {
      mockApi.getWorkerProfiles.mockResolvedValue([
        { ...mockWorkerProfiles[0], default_skill_ids: [11, 12] },
        mockWorkerProfiles[1],
      ])
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.selectedSkillIds).toEqual([11])
      wrapper.vm.handleSkillInheritanceUpdate(false)
      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ skill_ids: [11] })
      )
    })

    it('rejects malformed Worker Kit versions when enabling Skills', async () => {
      mockApi.getWorkerProfiles.mockResolvedValue([
        { ...mockWorkerProfiles[0], worker_kit_version: '1..0' },
        mockWorkerProfiles[1],
      ])
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.taskSkillSelectionSupported).toBe(false)
      expect(wrapper.vm.selectedSkillIds).toEqual([])
    })

    it('disables skill selection for deprecated baked-image profiles', async () => {
      await mountDrawer({ workerProfileId: 4 })
      await openDrawer()

      expect(wrapper.vm.taskSkillSelectionSupported).toBe(false)
      expect(wrapper.vm.selectedSkillIds).toEqual([])
      await wrapper.get('.execution-environment__summary').trigger('click')
      expect(wrapper.find('[data-testid="task-skill-selection"]').text())
        .toContain('createTask.skillsUnsupportedHint')
      const controls = wrapper.findAll('[data-testid="task-skill-selection"] .n-switch')
      expect(controls[0].attributes('disabled')).toBeDefined()
    })

    it('does not require code changes by default', async () => {
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.requireChanges).toBe(false)

      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ require_changes: false, session_mode: 'continue' })
      )
    })

    it('allows fresh-session mode when only a legacy workspace session may exist', async () => {
      await mountDrawer({ hasClaudeSession: false })
      await openDrawer()

      const switchButton = wrapper.find('[data-testid="task-session-mode-switch"]')
      const sessionMode = wrapper.find('[data-testid="task-session-mode"]')
      expect(switchButton.attributes('disabled')).toBeUndefined()
      expect(sessionMode.text()).toContain('createTask.startFreshSessionNoCurrent')
      expect(sessionMode.classes()).not.toContain('session-context-row--active')

      await switchButton.trigger('click')
      expect(sessionMode.classes()).toContain('session-context-row--active')
      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ session_mode: 'fresh' })
      )
    })

    it('submits fresh-session mode without changing the workspace options', async () => {
      await mountDrawer({ hasClaudeSession: true })
      await openDrawer()

      await wrapper.find('[data-testid="task-session-mode-switch"]').trigger('click')
      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ session_mode: 'fresh' })
      )
    })

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

    it('shows a field-level error when task mode is not selected and clears it after selection', async () => {
      await mountDrawer()
      await openDrawer()

      await submitCreate()

      expect(mockMessage.warning).toHaveBeenCalledWith('issue.pleaseSelectTaskMode')
      expect(mockApi.createTask).not.toHaveBeenCalled()
      expect(wrapper.vm.taskModeErrorVisible).toBe(true)
      expect(wrapper.find('.task-mode-label-row').text()).toContain('issue.taskMode')
      expect(wrapper.find('.task-mode-label-hint').text()).toBe('issue.taskModeManualHint')
      expect(wrapper.find('.task-mode-label-hint').classes()).toContain('task-mode-label-hint--error')
      expect(wrapper.findAll('.task-mode-card--error')).toHaveLength(2)

      await wrapper.find('.task-mode-card').trigger('click')
      await nextTick()

      expect(wrapper.vm.taskMode).toBe('execute')
      expect(wrapper.vm.taskModeErrorVisible).toBe(false)
      expect(wrapper.findAll('.task-mode-card--error')).toHaveLength(0)
      expect(wrapper.findAll('.task-mode-selector .n-radio')).toHaveLength(0)
      expect(wrapper.findAll('.task-mode-card__check')).toHaveLength(1)
      expect(wrapper.find('.task-mode-detail-reveal').exists()).toBe(true)

      await wrapper.findAll('.task-mode-card')[1].trigger('click')
      await nextTick()
      expect(wrapper.vm.taskMode).toBe('plan')
      expect(wrapper.find('.task-mode-detail-reveal').exists()).toBe(false)
      expect(wrapper.findAll('.task-mode-card__check')).toHaveLength(1)
    })

    it('shows a single top-right check on the selected priority card', async () => {
      await mountDrawer()
      await openDrawer()

      const priorityCards = wrapper.findAll('.priority-card')
      expect(priorityCards).toHaveLength(3)
      expect(priorityCards[1].attributes('aria-checked')).toBe('true')
      expect(wrapper.findAll('.priority-card__check')).toHaveLength(1)
      expect(wrapper.findAll('.priority-selector .n-radio')).toHaveLength(0)

      await priorityCards[0].trigger('click')
      await nextTick()

      expect(wrapper.vm.priority).toBe(0)
      expect(priorityCards[0].attributes('aria-checked')).toBe('true')
      expect(priorityCards[1].attributes('aria-checked')).toBe('false')
      expect(wrapper.findAll('.priority-card__check')).toHaveLength(1)
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

    it('uses accessible cards to switch the schedule mode and reveal its controls', async () => {
      await mountDrawer()
      await openDrawer()

      const scheduleCards = wrapper.findAll('.schedule-mode-card')
      expect(scheduleCards).toHaveLength(2)
      expect(scheduleCards[0].attributes('aria-checked')).toBe('true')
      expect(wrapper.find('.schedule-detail-reveal').exists()).toBe(false)

      await scheduleCards[1].trigger('click')
      await nextTick()

      expect(wrapper.vm.scheduleType).toBe('scheduled')
      expect(scheduleCards[1].attributes('aria-checked')).toBe('true')
      const scheduleDetail = wrapper.get('.schedule-detail-reveal')
      expect(scheduleDetail.find('.schedule-detail-reveal__inner').exists()).toBe(true)
      expect(scheduleDetail.find('.schedule-detail-panel').exists()).toBe(true)
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

    it('filters disabled providers from create options', async () => {
      mockApi.getProviders.mockResolvedValue([
        { id: 7, name: 'Default Provider', model: 'model-a', is_default: true, is_disabled: false },
        { id: 8, name: 'Disabled Provider', model: 'model-b', is_default: false, is_disabled: true },
      ])
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.providerOptions).toEqual([
        { label: 'Default Provider (model-a) ★', value: 7, disabled: false },
      ])
    })

    it('collapses the effective execution environment and updates its override summary', async () => {
      mockApi.getProviders.mockResolvedValue([
        { id: 7, name: 'Default Provider', model: 'model-a', is_default: true, is_disabled: false },
        { id: 8, name: 'Fast Provider', model: 'model-b', is_default: false, is_disabled: false },
      ])
      await mountDrawer()
      await openDrawer()

      const environmentSummary = wrapper.get('.execution-environment__summary')
      const sectionHeaders = wrapper.findAll('.task-form-section__header')
      expect(sectionHeaders).toHaveLength(3)
      expect(sectionHeaders[0].text()).toContain('createTask.contentSection')
      expect(sectionHeaders[1].text()).toContain('createTask.executionSection')
      expect(sectionHeaders[2].text()).toContain(
        'createTask.executionEnvironment'
      )
      expect(sectionHeaders[2].text()).toContain(
        'createTask.executionEnvironmentHint'
      )
      expect(wrapper.find('.execution-environment__icon').exists()).toBe(false)
      expect(environmentSummary.attributes('aria-expanded')).toBe('false')
      expect(environmentSummary.text()).toContain('createTask.executionEnvironmentDefault')
      expect(environmentSummary.text()).toContain('Java Worker')
      expect(environmentSummary.text()).toContain('Default Provider / model-a')
      expect(wrapper.find('.execution-environment__detail').exists()).toBe(false)

      await environmentSummary.trigger('click')
      expect(environmentSummary.attributes('aria-expanded')).toBe('true')
      expect(wrapper.find('.execution-environment__detail').exists()).toBe(true)
      expect(wrapper.findAll('.execution-environment__field')).toHaveLength(2)

      wrapper.vm.selectedProviderId = 8
      await nextTick()

      expect(environmentSummary.text()).toContain('createTask.executionEnvironmentOverride')
      expect(environmentSummary.text()).toContain('Fast Provider / model-b')
    })

    it('keeps the advanced disclosure text-first', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      await nextTick()

      expect(wrapper.find('.run-instruction-advanced__icon').exists()).toBe(false)
      expect(wrapper.get('.run-instruction-advanced__summary').text()).toContain(
        'runInstruction.advancedHint'
      )
    })

    it('automatically expands a warning when the default execution environment is incomplete', async () => {
      mockApi.getProviders.mockResolvedValue([
        { id: 7, name: 'Default Provider', model: 'model-a', is_default: true, is_disabled: true },
      ])
      await mountDrawer()
      await openDrawer()

      const summary = wrapper.get('.execution-environment__summary')
      expect(summary.attributes('aria-expanded')).toBe('true')
      expect(summary.text()).toContain('createTask.executionEnvironmentNeedsAttention')
      expect(wrapper.get('.execution-environment__warning').text()).toContain(
        'createTask.executionEnvironmentMissing'
      )
    })

    it('does not block creation when provider is left to issue default', async () => {
      mockApi.getProviders.mockResolvedValue([
        { id: 7, name: 'Default Provider', model: 'model-a', is_default: true, is_disabled: true },
      ])
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      await submitCreate()

      expect(mockMessage.warning).not.toHaveBeenCalledWith('config.providers.noEnabledProvider')
      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.not.objectContaining({ provider_id: expect.anything() })
      )
    })

    it('creates task with the issue worker and selected provider', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.taskMode = 'execute'
      wrapper.vm.selectedProviderId = 7
      wrapper.vm.runInstructionTemplate = 'Worker execute {{user_prompt}}'
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          provider_id: 7
        })
      )
      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.not.objectContaining({ worker_profile_id: expect.anything() })
      )
    })

    it('shows the pinned worker profile as read-only execution context', async () => {
      await mountDrawer()
      await openDrawer()

      expect(wrapper.get('.execution-environment__summary').text()).toContain('Java Worker')
      await wrapper.get('.execution-environment__summary').trigger('click')
      expect(
        wrapper.findAllComponents({ name: 'NSelect' }).map(select => select.props('placeholder'))
      ).toContain('createTask.selectProvider')
    })

    it('shows the issue worker and uses its run instruction defaults', async () => {
      await mountDrawer({ workerProfileId: 4 })
      await openDrawer()

      expect(wrapper.get('.execution-environment__summary').text()).toContain('Python Worker')

      wrapper.vm.selectTaskMode('execute')

      expect(wrapper.vm.runInstructionTemplate).toBe('Python execute {{user_prompt}}')
    })

    it('restores the provider override while preserving the issue worker', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.selectedProviderId = 7
      await nextTick()
      await wrapper.get('.execution-environment__summary').trigger('click')
      await wrapper.get('.execution-environment__footer button').trigger('click')

      expect(wrapper.vm.selectedProviderId).toBeNull()
      expect(wrapper.vm.effectiveWorkerProfile?.id).toBe(3)
      expect(wrapper.vm.executionEnvironmentExpanded).toBe(false)
    })

    it('submits a manually edited run instruction template on create', async () => {
      await mountDrawer()
      await openDrawer()

      wrapper.vm.selectTaskMode('execute')
      wrapper.vm.handleRunInstructionInput('Custom {{user_prompt}}')
      await submitCreate()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({ run_instruction_template: 'Custom {{user_prompt}}' })
      )
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

      wrapper.vm.prompt = ''
      wrapper.vm.handleTemplateItemClick(mockTemplates[0])

      expect(wrapper.vm.prompt).toBe('Fix {{issue_type}}')
      expect(wrapper.vm.promptVariableTips).toEqual({ issue_type: 'Bug type' })
    })

    it('keeps existing variable tips when a template has no tips', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.promptVariableTips = { old: 'tip' }
      wrapper.vm.prompt = ''
      wrapper.vm.handleTemplateItemClick(mockTemplates[1])

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

    it('filters active templates by all selected tags', async () => {
      mockApi.getPromptTemplates.mockResolvedValue([
        ...mockTemplates,
        { id: 3, name: 'Inactive', content: 'Hidden', tags: ['backend', 'review'], is_active: false, sort_order: 3, created_at: '2026-03-29T10:00:00Z', updated_at: '2026-03-29T10:00:00Z' },
        { id: 4, name: 'Backend only', content: 'Backend', tags: ['backend'], is_active: true, sort_order: 4, created_at: '2026-03-28T10:00:00Z', updated_at: '2026-03-28T10:00:00Z' },
      ])
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.selectedTemplateTags = ['backend', 'review']
      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      expect(wrapper.vm.filteredPromptTemplates.map((template: any) => template.name)).toEqual(['Bug Fix'])
      expect(wrapper.findAll('.prompt-template-dropdown__item')).toHaveLength(1)
      expect(wrapper.text()).toContain('backend')
      expect(wrapper.text()).toContain('review')
      expect(wrapper.text()).not.toContain('Inactive')
      expect(wrapper.text()).not.toContain('Backend only')
    })

    it('closes the tag filter dropdown after selecting tags', async () => {
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.templateTagFilterVisible = true
      wrapper.vm.handleTemplateTagFilterUpdate(['backend'])

      expect(wrapper.vm.selectedTemplateTags).toEqual(['backend'])
      expect(wrapper.vm.templateTagFilterVisible).toBe(false)
    })

    it('renders legacy templates without tags in the drawer', async () => {
      mockApi.getPromptTemplates.mockResolvedValue([
        { id: 5, name: 'Legacy', content: 'Legacy content', is_active: true, sort_order: 5, created_at: '2026-03-27T10:00:00Z', updated_at: '2026-03-27T10:00:00Z' },
      ])
      await mountDrawer({ issueDescription: '' })
      await openDrawer()

      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      expect(wrapper.findAll('.prompt-template-dropdown__item')).toHaveLength(1)
      expect(wrapper.text()).toContain('Legacy')
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

    it('clears slot capacity loading when schedule time changes during a request', async () => {
      await mountDrawer()
      await openDrawer()
      vi.useFakeTimers()
      let resolveCapacity!: (value: { available: number }) => void
      mockApi.getSlotCapacity.mockReturnValue(new Promise(resolve => {
        resolveCapacity = resolve
      }))

      wrapper.vm.scheduledAt = Date.now() + 3600000
      await nextTick()
      vi.advanceTimersByTime(350)
      await nextTick()
      expect(wrapper.vm.slotCapacityLoading).toBe(true)

      wrapper.vm.scheduledAt = null
      await nextTick()
      expect(wrapper.vm.slotCapacityLoading).toBe(false)

      resolveCapacity({ available: 5 })
      await flushPromises()
      expect(wrapper.vm.slotCapacityLoading).toBe(false)
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

    it('uses the immutable task runtime when checking skill support in edit mode', async () => {
      await mountEditDrawer({
        worker_profile_id: 4,
        worker_runtime_mode: 'mounted_kit',
        worker_kit_version: '0.3.5',
        skill_selection_source: 'task',
        skill_ids: [11],
      })
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.effectiveWorkerProfile.runtime_mode).toBe('baked_image')
      expect(wrapper.vm.taskSkillSelectionSupported).toBe(true)
      expect(wrapper.vm.selectedSkillIds).toEqual([11])
    })

    it('can explicitly clear a deleted frozen Skill snapshot', async () => {
      await mountEditDrawer({
        worker_profile_id: 3,
        worker_runtime_mode: 'mounted_kit',
        worker_kit_version: '0.3.5',
        skill_selection_source: 'task',
        skill_ids: [],
        skill_snapshots: [{
          id: null,
          name: 'deleted-review',
          description: 'Deleted after task creation',
          version_id: 91,
        }],
      })
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.changedTaskSkillSnapshots).toHaveLength(1)
      expect(wrapper.vm.executionEnvironmentNeedsAttention).toBe(true)
      expect(wrapper.vm.executionEnvironmentOpen).toBe(true)
      expect(wrapper.find('[data-testid="task-skill-snapshot-warning"]').exists()).toBe(true)
      wrapper.vm.applyCurrentSkillSelection()
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockApi.updateTask).toHaveBeenCalledWith(42, { skill_ids: [] })
    })

    it('warns when current Worker Profile defaults differ from the task snapshot', async () => {
      mockApi.getWorkerProfiles.mockResolvedValue([
        { ...mockWorkerProfiles[0], default_skill_ids: [11, 12] },
        mockWorkerProfiles[1],
      ])
      mockApi.getSkills.mockResolvedValue([
        { id: 11, name: 'review', description: 'Review changes', version_id: 101 },
        { id: 12, name: 'test', description: 'Run focused tests', version_id: 102 },
      ])
      await mountEditDrawer({
        worker_profile_id: 3,
        worker_runtime_mode: 'mounted_kit',
        worker_kit_version: '0.3.5',
        skill_selection_source: 'profile',
        skill_ids: [11],
        skill_snapshots: [{
          id: 11,
          name: 'review',
          description: 'Review changes',
          version_id: 101,
        }],
      })
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.changedTaskSkillSnapshots).toHaveLength(0)
      expect(wrapper.vm.profileDefaultSkillSelectionChanged).toBe(true)
      expect(wrapper.vm.executionEnvironmentNeedsAttention).toBe(true)
      expect(wrapper.vm.executionEnvironmentOpen).toBe(true)
      expect(wrapper.find('[data-testid="task-skill-snapshot-warning"]').text())
        .toContain('createTask.profileSkillSelectionChangedHint')

      wrapper.vm.applyCurrentSkillSelection()
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()

      expect(mockApi.updateTask).toHaveBeenCalledWith(42, { skill_ids: null })
    })

    it('does not offer current Profile Skills to an immutable baked-image task', async () => {
      await mountEditDrawer({
        worker_profile_id: 3,
        worker_runtime_mode: 'baked_image',
        worker_kit_version: null,
        skill_selection_source: 'profile',
        skill_ids: [],
        skill_snapshots: [],
      })
      await wrapper.setProps({ show: true })
      await flushPromises()

      expect(wrapper.vm.profileDefaultSkillSelectionChanged).toBe(true)
      expect(wrapper.vm.taskSkillSelectionSupported).toBe(false)
      expect(wrapper.vm.taskSkillSelectionNeedsAttention).toBe(false)
      expect(wrapper.find('[data-testid="task-skill-snapshot-warning"]').exists()).toBe(false)
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

  describe('run instruction templates', () => {
    it('shows run instructions only after a task mode is selected', async () => {
      await mountDrawer()
      await openDrawer()

      expect(wrapper.vm.taskMode).toBeNull()
      expect(wrapper.vm.runInstructionTemplate).toBe('')
      expect(wrapper.get('.n-drawer-content').attributes('data-native-scrollbar')).toBe('false')
      expect(wrapper.find('.run-instruction-advanced-reveal').exists()).toBe(false)

      wrapper.vm.selectTaskMode('execute')
      await nextTick()
      expect(wrapper.vm.runInstructionTemplate).toBe('Worker execute {{user_prompt}}')
      expect(wrapper.find('.run-instruction-advanced-reveal').exists()).toBe(true)
      expect(wrapper.find('.run-instruction-advanced__title').text()).toBe(
        'runInstruction.advanced'
      )
      expect(wrapper.find('.run-instruction-advanced__hint').text()).toBe(
        'runInstruction.advancedHint'
      )
      const advancedSummary = wrapper.get('.run-instruction-advanced__summary')
      expect(advancedSummary.attributes('aria-expanded')).toBe('false')
      expect(wrapper.find('.run-instruction-advanced__content-reveal').exists()).toBe(false)

      await advancedSummary.trigger('click')
      expect(advancedSummary.attributes('aria-expanded')).toBe('true')
      expect(wrapper.find('.run-instruction-advanced__content-reveal').exists()).toBe(true)
      expect(wrapper.getComponent({ name: 'RunInstructionTemplateEditor' }).props('embedded')).toBe(true)
    })

    it('leaves the execute default to the backend when Advanced is never opened', async () => {
      await mountDrawer()
      await openDrawer()
      wrapper.vm.selectTaskMode('execute')
      await submitCreate()
      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.not.objectContaining({ run_instruction_template: expect.anything() })
      )
      expect(wrapper.get('.run-instruction-advanced__summary').attributes('aria-expanded')).toBe('false')
    })

    it('keeps an edited template when mode replacement is declined', async () => {
      await mountDrawer()
      await openDrawer()
      wrapper.vm.selectTaskMode('execute')
      wrapper.vm.handleRunInstructionInput('Custom instruction')
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
      wrapper.vm.selectTaskMode('plan')
      expect(confirm).toHaveBeenCalled()
      expect(wrapper.vm.taskMode).toBe('plan')
      expect(wrapper.vm.runInstructionTemplate).toBe('Custom instruction')
      confirm.mockRestore()
    })

    it('uses the stored snapshot in edit mode and patches changed content', async () => {
      await mountDrawer({
        mode: 'edit',
        issueId: undefined,
        issueDescription: undefined,
        task: {
          id: 42,
          issue_id: 1,
          user_prompt: 'Original prompt',
          priority: 1,
          require_changes: true,
          provider_id: 7,
          task_mode: 'execute',
          run_instruction_template: 'Stored snapshot'
        }
      })
      await openDrawer()
      expect(wrapper.vm.runInstructionTemplate).toBe('Stored snapshot')
      expect(wrapper.vm.runInstructionDirty).toBe(false)
      wrapper.vm.handleRunInstructionInput('Changed snapshot')
      await wrapper.find('[data-testid="task-form-save-button"]').trigger('click')
      await flushPromises()
      expect(mockApi.updateTask).toHaveBeenCalledWith(
        42,
        expect.objectContaining({ run_instruction_template: 'Changed snapshot' })
      )
    })

    it('ignores a preview response after the template changes', async () => {
      let resolvePreview!: (value: any) => void
      mockApi.previewRunInstructionTemplate.mockImplementation(() => new Promise((resolve) => {
        resolvePreview = resolve
      }))
      await mountDrawer()
      await openDrawer()
      wrapper.vm.selectTaskMode('execute')

      const previewPromise = wrapper.vm.handleRunInstructionPreview()
      await nextTick()
      expect(wrapper.vm.previewLoading).toBe(true)

      wrapper.vm.handleRunInstructionInput('Changed while previewing')
      expect(wrapper.vm.previewLoading).toBe(false)
      expect(wrapper.vm.previewResult).toBe('')

      resolvePreview({
        rendered_prompt: 'Stale rendered prompt',
        used_placeholders: ['user_prompt'],
        unused_known_placeholders: []
      })
      await previewPromise
      await flushPromises()

      expect(wrapper.vm.previewResult).toBe('')
      expect(wrapper.vm.previewError).toBe('')
      expect(wrapper.vm.previewLoading).toBe(false)
    })
  })
})
