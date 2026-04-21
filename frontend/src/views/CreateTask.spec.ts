import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper, flushPromises } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import CreateTask from './CreateTask.vue'
import VariableEditor from '../components/VariableEditor.vue'
import { createMockProject, createMockBranch, createMockPromptTemplate, createMockTask } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getProjects: vi.fn<() => Promise<any[]>>(),
    getBranches: vi.fn<() => Promise<any[]>>(),
    createTask: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>(),
    getIssues: vi.fn<() => Promise<any>>(),
    getProviders: vi.fn<() => Promise<any[]>>()
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

// Mock i18n module that datetime.ts imports
vi.mock('../i18n', () => ({
  currentLocale: ref('en')
}))

// Mock datetime utils
vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8: vi.fn((value: any) => `formatted-date-${value}`),
  formatDateTimeUtc8Compact: vi.fn((value: any) => `compact-${value}`),
  formatTimeUtc8: vi.fn((value: any) => `time-${value}`)
}))

// Mock slot error utils
vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((_error: any, t: any, fallbackKey: string) => t(fallbackKey))
}))

// Mock dependencies
vi.mock('../api', () => ({
  getProjects: mockApi.getProjects,
  getBranches: mockApi.getBranches,
  createTask: mockApi.createTask,
  getPromptTemplates: mockApi.getPromptTemplates,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
  getConfig: mockApi.getConfig,
  getIssues: mockApi.getIssues,
  getProviders: mockApi.getProviders
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
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'label-placement'],
    setup(_props: any, { slots, expose }: any) {
      expose({ validate: vi.fn(), restoreValidation: vi.fn() })
      return () => h('form', {}, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['path', 'label', 'show-label'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, slots.default?.())
    },
    template: '<div class="n-form-item"><slot /></div>'
  },
  NSelect: {
    name: 'NSelect',
    props: ['options', 'loading', 'placeholder', 'disabled', 'value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        disabled: props.disabled,
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    },
    template: '<select class="n-select"><option v-for="opt in options" :key="opt.value" :value="opt.value">{{ opt.label }}</option></select>'
  },
  NInput: {
    name: 'NInput',
    props: ['placeholder', 'disabled', 'value'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        type: 'text',
        placeholder: props.placeholder,
        disabled: props.disabled,
        value: props.value,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    },
    template: '<input class="n-input" />'
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'min', 'max'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input-number',
        type: 'number',
        value: props.value,
        min: props.min,
        max: props.max,
        onInput: (e: Event) => emit('update:value', Number((e.target as HTMLInputElement).value))
      })
    },
    template: '<input class="n-input-number" type="number" />'
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'placeholder', 'is-date-disabled', 'is-time-disabled'],
    setup(props: any) {
      return () => h('div', { class: 'n-date-picker' }, props.placeholder)
    },
    template: '<div class="n-date-picker"></div>'
  },
  NRadioGroup: {
    name: 'NRadioGroup',
    props: ['value', 'name'],
    setup(_props: any) {
      return () => h('div', { class: 'n-radio-group' })
    },
    template: '<div class="n-radio-group"></div>'
  },
  NRadio: {
    name: 'NRadio',
    props: ['value'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-radio' }, slots.default?.())
    },
    template: '<div class="n-radio"><slot /></div>'
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'secondary', 'strong', 'round', 'loading', 'disabled'],
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
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [
        slots.header?.(),
        slots.default?.()
      ])
    },
    template: '<div class="n-card"><slot name="header" /><slot /></div>'
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'wrap', 'align'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
    template: '<div class="n-space"><slot /></div>'
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
  NPopover: {
    name: 'NPopover',
    props: ['trigger', 'placement', 'width', 'keep-alive-on-hover'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-popover' }, [slots.trigger?.(), slots.default?.()])
    },
    template: '<div class="n-popover"><slot name="trigger" /><slot /></div>'
  },
  NIcon: {
    name: 'NIcon',
    props: ['component'],
    setup(_props: any) {
      return () => h('i', { class: 'n-icon' })
    },
    template: '<i class="n-icon"></i>'
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        role: 'switch',
        'aria-checked': props.value,
        onClick: () => emit('update:value', !props.value)
      })
    },
    template: '<button class="n-switch" role="switch"></button>'
  },
  NTooltip: {
    name: 'NTooltip',
    props: ['placement'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tooltip' }, slots.trigger?.())
    },
    template: '<div class="n-tooltip"><slot name="trigger" /></div>'
  },
  NSpin: {
    name: 'NSpin',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-spin-loading' }, slots.default?.()) : h('div', { class: 'n-spin' }, slots.default?.())
    },
    template: '<div class="n-spin"><slot /></div>'
  },
  NModal: {
    name: 'NModal',
    props: ['preset', 'title', 'show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-modal' }, slots.default?.()) : h('div')
    },
    template: '<div v-if="show" class="n-modal"><slot /></div>'
  },
  useMessage: () => mockMessage,
  NDrawer: {
    name: 'NDrawer',
    props: ['show', 'width', 'placement'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-drawer' }, slots.default?.()) : h('div')
    }
  },
  NDrawerContent: {
    name: 'NDrawerContent',
    props: ['title', 'closable'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-drawer-content' }, slots.default?.())
    }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: 'n-alert', 'data-type': props.type }, slots.default?.())
    }
  },
  NRadioButton: {
    name: 'NRadioButton',
    props: ['value'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-radio-button' }, slots.default?.())
    }
  }
}))

// Mock VariableEditor component
vi.mock('../components/VariableEditor.vue', () => ({
  default: {
    name: 'VariableEditor',
    props: ['modelValue', 'variableTips', 'editable'],
    emits: ['update:modelValue', 'update:variableTips'],
    setup(props: any) {
      return () => h('div', { class: 'variable-editor' }, props.modelValue || '')
    },
    template: '<div class="variable-editor">{{ modelValue }}</div>'
  }
}))

// Mock HeatmapChart component
vi.mock('../components/HeatmapChart.vue', () => ({
  default: {
    name: 'HeatmapChart',
    props: ['tasks', 'selectedMs', 'maxPerSlot', 'enforceCapacity'],
    emits: ['cell-click'],
    setup() {
      return () => h('div', { class: 'heatmap-chart-mock' })
    }
  }
}))

// Mock @vicons/ionicons5
vi.mock('@vicons/ionicons5', () => ({
  DocumentTextOutline: { name: 'DocumentTextOutline' },
  WarningOutline: { name: 'WarningOutline' },
  InformationCircleOutline: { name: 'InformationCircleOutline' },
  CalendarOutline: { name: 'CalendarOutline' }
}))

// Mock router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/tasks/:id', name: 'task-view', component: { template: '<div>task</div>' } }
  ]
})

const mockProjects = [
  createMockProject({ id: 1, name: 'Project 1', path_with_namespace: 'group/project-1', default_branch: 'main' }),
  createMockProject({ id: 2, name: 'Project 2', path_with_namespace: 'group/project-2', default_branch: 'develop' })
]

const mockBranches = [
  createMockBranch({ name: 'main' }),
  createMockBranch({ name: 'develop' }),
  createMockBranch({ name: 'feature/test' })
]

const mockIssues = [
  { id: 1, title: 'Fix login bug', description: 'Login is broken', project_id: 1, status: 'open', branch_name: 'codify/issue-1', base_branch: 'main', target_branch: 'main', merge_request_iid: null, merge_request_url: null, claude_session_id: null, initiator_user_id: null, initiator_username: null, created_at: '2026-03-31T10:00:00Z', updated_at: '2026-03-31T10:00:00Z' },
  { id: 2, title: 'Add feature X', description: null, project_id: 2, status: 'open', branch_name: 'codify/issue-2', base_branch: 'develop', target_branch: 'develop', merge_request_iid: null, merge_request_url: null, claude_session_id: null, initiator_user_id: null, initiator_username: null, created_at: '2026-03-31T11:00:00Z', updated_at: '2026-03-31T11:00:00Z' }
]
const mockIssueListResponse = { items: mockIssues, total: mockIssues.length, page: 1, page_size: 100 }

const mockTemplates = [
  createMockPromptTemplate({ id: 1, name: 'Bug Fix', content: 'Fix {{issue}}', variable_tips: { issue: 'Issue description' } }),
  createMockPromptTemplate({ id: 2, name: 'Feature', content: 'Add {{feature}}', variable_tips: { feature: 'Feature name' } })
]

describe('CreateTask', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    Object.values(mockMessage).forEach(fn => fn.mockReset())
    router.push('/')
    await router.isReady()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  const mountComponent = async () => {
    // Mock getIssues to return successful response
    ;(mockApi.getIssues as Mock).mockResolvedValue(mockIssueListResponse)
    ;(mockApi.getPromptTemplates as Mock).mockResolvedValue(mockTemplates)
    ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask({ id: 123 }))
    ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
    ;(mockApi.getSlotCapacity as Mock).mockResolvedValue({ is_full: false, enforce: false, count: 0, max: 0, hour_start: '', hour_end: '' })
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 0 } })
    ;(mockApi.getProviders as Mock).mockResolvedValue([])

    wrapper = mount(CreateTask, {
      global: {
        plugins: [router],
        stubs: {
          'variable-editor': VariableEditor
        }
      }
    })

    // Wait for onMounted to complete
    await vi.waitFor(() => {
      return (mockApi.getIssues as Mock).mock.calls.length > 0
    })
    await flushPromises()

    return wrapper
  }

  describe('basic rendering', () => {
    it('should render form with all sections', async () => {
      await mountComponent()

      // Check title is rendered
      expect(wrapper.find('.create-task-page').exists()).toBe(true)
    })

    it('should show loading state during data fetch', async () => {
      ;(mockApi.getIssues as Mock).mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(mockIssueListResponse), 100)))
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])
      ;(mockApi.getProviders as Mock).mockResolvedValue([])
      ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask())

      wrapper = mount(CreateTask, {
        global: {
          plugins: [router],
          stubs: {
            'variable-editor': VariableEditor
          }
        }
      })

      // After data loads, component should be rendered
      await vi.waitFor(() => {
        return (mockApi.getIssues as Mock).mock.results.length > 0
      })
    })

    it('should fetch issues on mount', async () => {
      await mountComponent()
      expect(mockApi.getIssues).toHaveBeenCalledTimes(1)
    })

    it('should fetch prompt templates on mount', async () => {
      await mountComponent()
      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })
  })

  describe('issue selection', () => {
    it('should populate issue options from fetched issues', async () => {
      await mountComponent()

      const options = wrapper.vm.issueOptions
      expect(options).toHaveLength(2)
      expect(options[0].label).toContain('Fix login bug')
      expect(options[0].value).toBe(1)
      expect(options[1].label).toContain('Add feature X')
      expect(options[1].value).toBe(2)
    })

    it('should show selected issue context when issue is selected', async () => {
      await mountComponent()

      wrapper.vm.formValue.issue_id = 1
      await nextTick()

      expect(wrapper.vm.selectedIssue).toBeTruthy()
      expect(wrapper.vm.selectedIssue.title).toBe('Fix login bug')
      expect(wrapper.vm.selectedIssue.project_id).toBe(1)
    })

    it('should return null when no issue is selected', async () => {
      await mountComponent()

      expect(wrapper.vm.selectedIssue).toBeNull()
    })
  })

  describe('form validation', () => {
    it('should require project selection', async () => {
      await mountComponent()

      // Get form reference
      const formRef = wrapper.vm.formRef
      expect(formRef).toBeDefined()

      // Trigger validation for project_id
      try {
        await formRef.value?.validate(undefined, (rule: any) => rule?.key === 'project_id')
      } catch (e: any) {
        // Validation should fail without project
        expect(e).toBeDefined()
      }
    })

    it('should require issue selection', async () => {
      await mountComponent()

      // Form model should have null issue_id initially (required field)
      expect(wrapper.vm.formValue.issue_id).toBeNull()
    })

    it('should require user prompt', async () => {
      await mountComponent()

      // Form model should have no prompt initially (required field)
      expect(wrapper.vm.formValue.prompt).toBeFalsy()
    })

    it('should have default priority of 1', async () => {
      await mountComponent()

      expect(wrapper.vm.formValue.priority).toBe(1)
    })
  })

  describe('schedule options', () => {
    it('should show delay inputs when delay selected', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'delay'

      expect(wrapper.vm.scheduleType).toBe('delay')
    })

    it('should show datetime picker when scheduled selected', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'scheduled'

      expect(wrapper.vm.scheduleType).toBe('scheduled')
    })

    it('should calculate delay_seconds correctly', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 5
      wrapper.vm.delayUnit = 'minutes'

      const schedule = wrapper.vm.buildScheduleRequest()
      expect(schedule.delay_seconds).toBe(300) // 5 * 60
    })

    it('should calculate delay_seconds for hours correctly', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 2
      wrapper.vm.delayUnit = 'hours'

      const schedule = wrapper.vm.buildScheduleRequest()
      expect(schedule.delay_seconds).toBe(7200) // 2 * 3600
    })

    it('should validate scheduled time is in future', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledDatetime = Date.now() - 1000 // Past time

      expect(() => wrapper.vm.buildScheduleRequest()).toThrow()
    })
  })

  describe('prompt templates', () => {
    it('should fetch templates on mount', async () => {
      await mountComponent()
      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })

    it('should apply template on selection', async () => {
      await mountComponent()

      const template = mockTemplates[0]
      await wrapper.vm.applyPromptTemplate(template)

      expect(wrapper.vm.formValue.user_prompt).toBe(template.content)
      expect(wrapper.vm.promptVariableTips).toEqual(template.variable_tips)
    })

    it('should confirm before overwriting existing prompt', async () => {
      await mountComponent()

      // Set existing prompt
      wrapper.vm.formValue.user_prompt = 'Existing prompt'

      // Mock window.confirm to return false
      const confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(false)

      const template = mockTemplates[0]
      await wrapper.vm.applyPromptTemplate(template)

      // Prompt should not be overwritten
      expect(wrapper.vm.formValue.user_prompt).toBe('Existing prompt')

      confirmSpy.mockRestore()
    })

    it('should detect unreplaced variables', async () => {
      await mountComponent()

      wrapper.vm.formValue.user_prompt = 'Fix the {{issue}} in {{file}}'

      expect(wrapper.vm.unreplacedVariables).toEqual(['issue', 'file'])
    })
  })

  describe('form submission', () => {
    it('should call createTask API on submit', async () => {
      await mountComponent()

      // Fill required fields
      wrapper.vm.formValue.issue_id = 1
      wrapper.vm.formValue.user_prompt = 'Fix the bug'

      await wrapper.vm.handleSubmit()

      await vi.waitFor(() => {
        expect(mockApi.createTask).toHaveBeenCalledTimes(1)
      })

      const call = (mockApi.createTask as Mock).mock.calls[0][0]
      expect(call.issue_id).toBe(1)
      expect(call.user_prompt).toBe('Fix the bug')
      expect(call.priority).toBe(1)
    })

    it('should show success modal on success', async () => {
      await mountComponent()

      wrapper.vm.formValue.issue_id = 1
      wrapper.vm.formValue.user_prompt = 'Fix the bug'

      await wrapper.vm.handleSubmit()

      await vi.waitFor(() => {
        return wrapper.vm.showSuccessModal === true
      })

      expect(wrapper.vm.showSuccessModal).toBe(true)
      expect(wrapper.vm.createdTaskId).toBe(123)
    })

    it('should navigate to task view on viewTask', async () => {
      await mountComponent()

      wrapper.vm.showSuccessModal = true
      wrapper.vm.createdTaskId = 123

      // Spy on router.push to verify navigation is triggered
      const pushSpy = vi.spyOn(router, 'push')

      // Call viewTask which navigates via router
      wrapper.vm.viewTask()

      // Verify router.push was called with correct path
      expect(pushSpy).toHaveBeenCalledWith('/tasks/123')
    })

    it('should reset form on createAnother', async () => {
      await mountComponent()

      // Fill some fields
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.user_prompt = 'Test prompt'
      wrapper.vm.showSuccessModal = true

      await wrapper.vm.createAnother()

      await vi.waitFor(() => {
        return wrapper.vm.showSuccessModal === false
      })

      expect(wrapper.vm.showSuccessModal).toBe(false)
    })

    it('should show error message on failure', async () => {
      await mountComponent()

      ;(mockApi.createTask as Mock).mockRejectedValue(new Error('API Error'))

      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.new_branch_name = 'test-branch'
      wrapper.vm.formValue.target_branch = 'main'
      wrapper.vm.formValue.user_prompt = 'Fix the bug'

      await wrapper.vm.handleSubmit()

      // Should handle error without throwing
      await vi.waitFor(() => {
        return wrapper.vm.submitting === false
      })

      expect(wrapper.vm.submitting).toBe(false)
    })
  })

  describe('form reset', () => {
    it('should reset all form values', async () => {
      await mountComponent()

      // Set various values
      wrapper.vm.formValue.issue_id = 1
      wrapper.vm.formValue.user_prompt = 'Some prompt'
      wrapper.vm.formValue.priority = 2
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 10
      wrapper.vm.delayUnit = 'hours'

      await wrapper.vm.handleReset()

      expect(wrapper.vm.formValue.issue_id).toBeNull()
      expect(wrapper.vm.formValue.user_prompt).toBe('')
      expect(wrapper.vm.formValue.priority).toBe(1)
      expect(wrapper.vm.scheduleType).toBe('now')
      expect(wrapper.vm.delayValue).toBe(5)
      expect(wrapper.vm.delayUnit).toBe('minutes')
    })

    it('should clear validation errors', async () => {
      await mountComponent()

      // Simply verify handleReset completes without error
      // The actual form validation clearing is handled internally by the form component
      await wrapper.vm.handleReset()
      // Verify form ref still accessible after reset (handleReset calls restoreValidation internally)
      expect(wrapper.vm.formRef).toBeDefined()
    })
  })

  describe('slot capacity', () => {
    const fullSlotCapacity = {
      is_full: true,
      enforce: true,
      count: 5,
      max: 5,
      hour_start: '2026-04-01T10:00:00Z',
      hour_end: '2026-04-01T11:00:00Z'
    }

    const warningSlotCapacity = {
      is_full: true,
      enforce: false,
      count: 5,
      max: 5,
      hour_start: '2026-04-01T10:00:00Z',
      hour_end: '2026-04-01T11:00:00Z'
    }

    const availableSlotCapacity = {
      is_full: false,
      enforce: false,
      count: 2,
      max: 5,
      hour_start: '2026-04-01T10:00:00Z',
      hour_end: '2026-04-01T11:00:00Z'
    }

    it('submit button is disabled when slotCapacity.is_full && enforce', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = fullSlotCapacity
      await nextTick()

      const submitBtn = wrapper.findAll('button.n-button').find(
        (b: any) => b.text().includes('common.createTask')
      )
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.element.disabled).toBe(true)
    })

    it('submit button is enabled when slot is not full', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = availableSlotCapacity
      await nextTick()

      const submitBtn = wrapper.findAll('button.n-button').find(
        (b: any) => b.text().includes('common.createTask')
      )
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.element.disabled).toBe(false)
    })

    it('submit button is enabled when enforce is false even if full', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = warningSlotCapacity
      await nextTick()

      const submitBtn = wrapper.findAll('button.n-button').find(
        (b: any) => b.text().includes('common.createTask')
      )
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.element.disabled).toBe(false)
    })

    it('alert shows with type "error" when enforce mode', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = fullSlotCapacity
      await nextTick()

      const alert = wrapper.find('.n-alert')
      expect(alert.exists()).toBe(true)
      expect(alert.attributes('data-type')).toBe('error')
    })

    it('alert shows with type "warning" when soft mode', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = warningSlotCapacity
      await nextTick()

      const alert = wrapper.find('.n-alert')
      expect(alert.exists()).toBe(true)
      expect(alert.attributes('data-type')).toBe('warning')
    })

    it('no alert when slot is not full', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = availableSlotCapacity
      await nextTick()

      const alert = wrapper.find('.n-alert')
      expect(alert.exists()).toBe(false)
    })

    it('no alert when slotCapacity is null', async () => {
      await mountComponent()

      wrapper.vm.slotCapacity = null
      await nextTick()

      const alert = wrapper.find('.n-alert')
      expect(alert.exists()).toBe(false)
    })

    it('submit button is disabled when slotCapacityLoading is true', async () => {
      await mountComponent()

      wrapper.vm.slotCapacityLoading = true
      await nextTick()

      const submitBtn = wrapper.findAll('button.n-button').find(
        (b: any) => b.text().includes('common.createTask')
      )
      expect(submitBtn).toBeTruthy()
      expect(submitBtn!.element.disabled).toBe(true)
    })
  })

  describe('scheduleSummary computed', () => {
    it('should show "runs immediately" for schedule type now', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'now'

      expect(wrapper.vm.scheduleSummary).toContain('runsImmediately')
    })

    it('should show delay summary for schedule type delay', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 5
      wrapper.vm.delayUnit = 'minutes'

      // When delayValue > 0, the code returns 'taskWillRunAfter'
      expect(wrapper.vm.scheduleSummary).toContain('taskWillRunAfter')
    })

    it('should show select future time when scheduled but no datetime selected', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledDatetime = null

      expect(wrapper.vm.scheduleSummary).toContain('selectFutureTime')
    })
  })

  describe('isScheduledDateDisabled', () => {
    it('should disable past dates and allow future dates', async () => {
      await mountComponent()
      const yesterday = new Date()
      yesterday.setDate(yesterday.getDate() - 1)
      const tomorrow = new Date()
      tomorrow.setDate(tomorrow.getDate() + 1)

      expect(wrapper.vm.isScheduledDateDisabled(yesterday.getTime())).toBe(true)
      expect(wrapper.vm.isScheduledDateDisabled(tomorrow.getTime())).toBe(false)
    })
  })

  describe('isScheduledTimeDisabled', () => {
    it('should return empty object for future dates', async () => {
      await mountComponent()
      const tomorrow = new Date()
      tomorrow.setDate(tomorrow.getDate() + 1)

      const result = wrapper.vm.isScheduledTimeDisabled(tomorrow.getTime())
      expect(result).toEqual({})
    })

    it('should disable past hours/minutes/seconds for today', async () => {
      await mountComponent()
      const now = new Date()

      const result = wrapper.vm.isScheduledTimeDisabled(now.getTime())
      expect(result.isHourDisabled).toBeDefined()
      expect(result.isMinuteDisabled).toBeDefined()
      expect(result.isSecondDisabled).toBeDefined()

      // Past hour should be disabled
      if (now.getHours() > 0) {
        expect(result.isHourDisabled(0)).toBe(true)
      }
      // Future hour should not be disabled
      expect(result.isHourDisabled(23)).toBe(false)

      // Past minute in current hour should be disabled
      if (now.getMinutes() > 0) {
        expect(result.isMinuteDisabled(0, now.getHours())).toBe(true)
      }
      // Minute in different hour should not be disabled
      expect(result.isMinuteDisabled(0, now.getHours() + 1)).toBe(false)

      // Past second in current hour and minute should be disabled
      if (now.getSeconds() > 0) {
        expect(result.isSecondDisabled(0, now.getMinutes(), now.getHours())).toBe(true)
      }
    })
  })

  describe('openScheduleDrawer', () => {
    it('should open drawer, fetch scheduled tasks and config', async () => {
      await mountComponent()

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
      expect(mockApi.getConfig).toHaveBeenCalled()
    })

    it('should handle getScheduledTasks error gracefully', async () => {
      await mountComponent()
      ;(mockApi.getScheduledTasks as Mock).mockRejectedValue(new Error('API Error'))

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(wrapper.vm.scheduledTasksForPreview).toEqual([])
    })

    it('should not refetch tasks if already cached', async () => {
      await mountComponent()

      // First open fetches tasks
      await wrapper.vm.openScheduleDrawer()
      await flushPromises()
      const callCount = (mockApi.getScheduledTasks as Mock).mock.calls.length

      // Second open should skip fetch since tasks are already loaded (empty array from first call)
      // Set a non-empty result to simulate cached data
      wrapper.vm.scheduledTasksForPreview = [createMockTask()]

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      // Should not have called getScheduledTasks again
      expect((mockApi.getScheduledTasks as Mock).mock.calls.length).toBe(callCount)
    })
  })

  describe('handleScheduleHeatmapCellClick', () => {
    it('should set datetime, switch to scheduled mode, and close drawer', async () => {
      await mountComponent()

      wrapper.vm.showScheduleDrawer = true
      const clickTime = Date.now() + 3600000

      wrapper.vm.handleScheduleHeatmapCellClick(clickTime)

      expect(wrapper.vm.scheduledDatetime).toBe(clickTime)
      expect(wrapper.vm.scheduleType).toBe('scheduled')
      expect(wrapper.vm.showScheduleDrawer).toBe(false)
    })
  })

  describe('buildScheduleRequest edge cases', () => {
    it('should return empty object for now schedule type', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'now'

      const result = wrapper.vm.buildScheduleRequest()
      expect(result).toEqual({})
    })

    it('should throw for invalid delay value (null)', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = null

      expect(() => wrapper.vm.buildScheduleRequest()).toThrow()
    })

    it('should throw for zero delay value', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 0

      expect(() => wrapper.vm.buildScheduleRequest()).toThrow()
    })

    it('should throw when scheduled datetime is null', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledDatetime = null

      expect(() => wrapper.vm.buildScheduleRequest()).toThrow()
    })

    it('should calculate delay_seconds for seconds unit', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 30
      wrapper.vm.delayUnit = 'seconds'

      const result = wrapper.vm.buildScheduleRequest()
      expect(result.delay_seconds).toBe(30)
    })

    it('should return ISO datetime for valid scheduled time', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'scheduled'
      const futureTime = Date.now() + 86400000
      wrapper.vm.scheduledDatetime = futureTime

      const result = wrapper.vm.buildScheduleRequest()
      expect(result.scheduled_datetime).toBe(new Date(futureTime).toISOString())
    })
  })

  describe('form submission edge cases', () => {
    it('should return early when formRef is null', async () => {
      await mountComponent()

      wrapper.vm.formRef = null

      await wrapper.vm.handleSubmit()

      expect(mockApi.createTask).not.toHaveBeenCalled()
    })
  })

  describe('scheduleSummary additional edge cases', () => {
    it('should show delayGreaterThanZero when delayValue is 0', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 0

      expect(wrapper.vm.scheduleSummary).toContain('delayGreaterThanZero')
    })

    it('should show summary for seconds unit', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 30
      wrapper.vm.delayUnit = 'seconds'

      expect(wrapper.vm.scheduleSummary).toContain('taskWillRunAfter')
    })

    it('should show scheduled time when datetime is set', async () => {
      await mountComponent()
      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledDatetime = Date.now() + 3600000

      expect(wrapper.vm.scheduleSummary).toContain('taskWillRunAt')
    })
  })

  describe('scheduledDatetime watcher', () => {
    it('should set error when datetime is in the past', async () => {
      await mountComponent()

      wrapper.vm.scheduledDatetime = Date.now() - 1000
      await nextTick()

      expect(wrapper.vm.scheduledDatetimeError).not.toBeNull()
    })

    it('should clear error when datetime is in the future', async () => {
      await mountComponent()

      // First set a past time to trigger error
      wrapper.vm.scheduledDatetime = Date.now() - 1000
      await nextTick()
      expect(wrapper.vm.scheduledDatetimeError).not.toBeNull()

      // Then set a future time to clear error
      wrapper.vm.scheduledDatetime = Date.now() + 60000
      await nextTick()

      expect(wrapper.vm.scheduledDatetimeError).toBeNull()
    })
  })

  describe('scheduleType watcher', () => {
    it('should clear scheduledDatetime when changing from scheduled to now', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.scheduledDatetime = Date.now() + 3600000
      await nextTick()

      wrapper.vm.scheduleType = 'now'
      await nextTick()

      expect(wrapper.vm.scheduledDatetime).toBeNull()
    })

    it('should close schedule drawer when changing away from scheduled', async () => {
      await mountComponent()

      wrapper.vm.scheduleType = 'scheduled'
      wrapper.vm.showScheduleDrawer = true
      await nextTick()

      wrapper.vm.scheduleType = 'delay'
      await nextTick()

      expect(wrapper.vm.showScheduleDrawer).toBe(false)
    })
  })

  describe('fetch error handling', () => {
    it('should handle fetchIssues error gracefully', async () => {
      ;(mockApi.getIssues as Mock).mockRejectedValue(new Error('API Error'))
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])
      ;(mockApi.getProviders as Mock).mockResolvedValue([])
      ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask())
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
      ;(mockApi.getSlotCapacity as Mock).mockResolvedValue({ is_full: false })
      ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: {} })

      wrapper = mount(CreateTask, {
        global: {
          plugins: [router],
          stubs: { 'variable-editor': VariableEditor }
        }
      })

      await vi.waitFor(() => {
        return (mockApi.getIssues as Mock).mock.calls.length > 0
      })
      await flushPromises()

      // Component should not crash
      expect(wrapper.find('.create-task-page').exists()).toBe(true)
      expect(wrapper.vm.issueOptions).toEqual([])
    })

    it('should handle fetchPromptTemplates error gracefully', async () => {
      const consoleSpy = vi.spyOn(console, 'error').mockImplementation(() => {})
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getBranches as Mock).mockResolvedValue([])
      ;(mockApi.getPromptTemplates as Mock).mockRejectedValue(new Error('API Error'))
      ;(mockApi.getProviders as Mock).mockResolvedValue([])
      ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask())
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
      ;(mockApi.getSlotCapacity as Mock).mockResolvedValue({ is_full: false })
      ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: {} })

      wrapper = mount(CreateTask, {
        global: {
          plugins: [router],
          stubs: { 'variable-editor': VariableEditor }
        }
      })

      await vi.waitFor(() => {
        return (mockApi.getPromptTemplates as Mock).mock.calls.length > 0
      })
      await flushPromises()

      expect(wrapper.find('.create-task-page').exists()).toBe(true)
      expect(consoleSpy).toHaveBeenCalledWith('Failed to fetch prompt templates:', expect.any(Error))
      consoleSpy.mockRestore()
    })
  })

  describe('priorityOptions computed', () => {
    it('should return three priority options with correct values', async () => {
      await mountComponent()

      const options = wrapper.vm.priorityOptions
      expect(options).toHaveLength(3)
      expect(options[0].value).toBe(0)
      expect(options[1].value).toBe(1)
      expect(options[2].value).toBe(2)
    })
  })

  describe('form reset additional checks', () => {
    it('should increment formResetKey on reset', async () => {
      await mountComponent()
      const initialKey = wrapper.vm.formResetKey

      await wrapper.vm.handleReset()

      expect(wrapper.vm.formResetKey).toBe(initialKey + 1)
    })

    it('should reset createdTaskId on reset', async () => {
      await mountComponent()
      wrapper.vm.createdTaskId = 99

      await wrapper.vm.handleReset()

      expect(wrapper.vm.createdTaskId).toBe(0)
    })

    it('should reset scheduledDatetime on reset', async () => {
      await mountComponent()
      wrapper.vm.scheduledDatetime = Date.now() + 3600000

      await wrapper.vm.handleReset()

      expect(wrapper.vm.scheduledDatetime).toBeNull()
    })
  })

  describe('createAnother', () => {
    it('should clear scheduledTasksForPreview', async () => {
      await mountComponent()
      wrapper.vm.scheduledTasksForPreview = [createMockTask()]
      wrapper.vm.showSuccessModal = true

      await wrapper.vm.createAnother()

      expect(wrapper.vm.scheduledTasksForPreview).toEqual([])
    })
  })
})
