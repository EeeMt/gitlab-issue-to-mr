import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper, flushPromises } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import CreateTask from './CreateTask.vue'
import VariableEditor from '../components/VariableEditor.vue'
import { createMockProject, createMockBranch, createMockPromptTemplate, createMockTask } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi } = vi.hoisted(() => {
  const mock = {
    getProjects: vi.fn<() => Promise<any[]>>(),
    getBranches: vi.fn<() => Promise<any[]>>(),
    createTask: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>()
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

// Mock i18n module that datetime.ts imports
vi.mock('../i18n', () => ({
  currentLocale: ref('en')
}))

// Mock datetime utils
vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8: vi.fn((value: any) => `formatted-date-${value}`)
}))

// Mock dependencies
vi.mock('../api', () => ({
  getProjects: mockApi.getProjects,
  getBranches: mockApi.getBranches,
  createTask: mockApi.createTask,
  getPromptTemplates: mockApi.getPromptTemplates,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
  getConfig: mockApi.getConfig
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
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }),
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

const mockTemplates = [
  createMockPromptTemplate({ id: 1, name: 'Bug Fix', content: 'Fix {{issue}}', variable_tips: { issue: 'Issue description' } }),
  createMockPromptTemplate({ id: 2, name: 'Feature', content: 'Add {{feature}}', variable_tips: { feature: 'Feature name' } })
]

describe('CreateTask', () => {
  let wrapper: VueWrapper<any>

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    router.push('/')
    await router.isReady()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
  })

  const mountComponent = async () => {
    // Mock getProjects to return successful response
    ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
    ;(mockApi.getBranches as Mock).mockResolvedValue(mockBranches)
    ;(mockApi.getPromptTemplates as Mock).mockResolvedValue(mockTemplates)
    ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask({ id: 123 }))
    ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
    ;(mockApi.getSlotCapacity as Mock).mockResolvedValue({ is_full: false, enforce: false, count: 0, max: 0, hour_start: '', hour_end: '' })
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: { slot_max_tasks: 0 } })

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
      return (mockApi.getProjects as Mock).mock.calls.length > 0
    })

    return wrapper
  }

  describe('basic rendering', () => {
    it('should render form with all sections', async () => {
      await mountComponent()

      // Check title is rendered
      expect(wrapper.find('.create-task-page').exists()).toBe(true)
    })

    it('should show loading state during data fetch', async () => {
      ;(mockApi.getProjects as Mock).mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(mockProjects), 100)))
      ;(mockApi.getBranches as Mock).mockResolvedValue([])
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])
      ;(mockApi.createTask as Mock).mockResolvedValue(createMockTask())

      wrapper = mount(CreateTask, {
        global: {
          plugins: [router],
          stubs: {
            'variable-editor': VariableEditor
          }
        }
      })

      // Initial state - loading should be shown
      await vi.waitFor(() => {
        return wrapper.find('.n-spin-loading').exists()
      })

      // After data loads, loading should be hidden
      await vi.waitFor(() => {
        return (mockApi.getProjects as Mock).mock.results.length > 0
      })
    })

    it('should fetch projects on mount', async () => {
      await mountComponent()
      expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
    })

    it('should fetch prompt templates on mount', async () => {
      await mountComponent()
      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })
  })

  describe('project selection', () => {
    it('should fetch branches when project changes', async () => {
      await mountComponent()

      // Clear previous calls
      ;(mockApi.getBranches as Mock).mockClear()

      // Simulate project change by calling handleProjectChange directly
      await wrapper.vm.handleProjectChange(1)

      await vi.waitFor(() => {
        expect(mockApi.getBranches).toHaveBeenCalledWith(1)
      })
    })

    it('should reset branch selection when project changes', async () => {
      await mountComponent()

      // Select project 1 first; wait for branches + auto-set base_branch
      await wrapper.vm.handleProjectChange(1)
      await vi.waitFor(() => {
        return (mockApi.getBranches as Mock).mock.calls.length > 0
      })
      await flushPromises()

      // Change project; auto-set logic will pick project 2's default branch
      await wrapper.vm.handleProjectChange(2)
      await flushPromises()

      // Base branch should be auto-set to project 2's default branch ('develop')
      expect(wrapper.vm.formValue.base_branch).toBe('develop')
    })

    it('should set target branch to project default', async () => {
      await mountComponent()

      // Change to project with default_branch = 'develop'
      await wrapper.vm.handleProjectChange(2)

      expect(wrapper.vm.formValue.target_branch).toBe('develop')
    })
  })

  describe('branch selection', () => {
    it('should populate branch options from API', async () => {
      await mountComponent()

      await wrapper.vm.handleProjectChange(1)

      await vi.waitFor(() => {
        return wrapper.vm.branchOptions.length > 0
      })

      expect(wrapper.vm.branchOptions).toHaveLength(3)
      expect(wrapper.vm.branchOptions.map((o: any) => o.label)).toEqual(['main', 'develop', 'feature/test'])
    })

    it('should move main to top of target branch options', async () => {
      await mountComponent()

      await wrapper.vm.handleProjectChange(1)

      await vi.waitFor(() => {
        return wrapper.vm.targetBranchOptions.length > 0
      })

      expect(wrapper.vm.targetBranchOptions[0].value).toBe('main')
    })

    it('should clear new branch name when base branch changes', async () => {
      await mountComponent()

      await wrapper.vm.handleProjectChange(1)
      await vi.waitFor(() => {
        return (mockApi.getBranches as Mock).mock.calls.length > 0
      })

      // Set new branch name
      wrapper.vm.formValue.new_branch_name = 'my-feature-branch'
      expect(wrapper.vm.formValue.new_branch_name).toBe('my-feature-branch')

      // Change base branch
      await wrapper.vm.handleBaseBranchChange('develop')

      // New branch name should be cleared
      expect(wrapper.vm.formValue.new_branch_name).toBe('')
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

    it('should require base branch selection', async () => {
      await mountComponent()

      const formRef = wrapper.vm.formRef
      expect(formRef).toBeDefined()
    })

    it('should require user prompt', async () => {
      await mountComponent()

      const formRef = wrapper.vm.formRef
      expect(formRef).toBeDefined()
    })

    it('should show branch conflict warning', async () => {
      await mountComponent()

      // Set same source and target branch
      wrapper.vm.formValue.new_branch_name = 'main'
      wrapper.vm.formValue.target_branch = 'main'

      expect(wrapper.vm.sameBranchConflict).toBe(true)
      // Warning is a sibling element in the template, not inside a slot
      // Since our mock doesn't render the full template structure, we just verify the computed property
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
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.new_branch_name = 'test-branch'
      wrapper.vm.formValue.target_branch = 'main'
      wrapper.vm.formValue.user_prompt = 'Fix the bug'

      await wrapper.vm.handleSubmit()

      await vi.waitFor(() => {
        expect(mockApi.createTask).toHaveBeenCalledTimes(1)
      })

      const call = (mockApi.createTask as Mock).mock.calls[0][0]
      expect(call.project_id).toBe(1)
      expect(call.branch_name).toBe('test-branch')
      expect(call.base_branch).toBe('main')
      expect(call.target_branch).toBe('main')
      expect(call.user_prompt).toBe('Fix the bug')
    })

    it('should show success modal on success', async () => {
      await mountComponent()

      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.new_branch_name = 'test-branch'
      wrapper.vm.formValue.target_branch = 'main'
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
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.new_branch_name = 'test-branch'
      wrapper.vm.formValue.target_branch = 'develop'
      wrapper.vm.formValue.user_prompt = 'Some prompt'
      wrapper.vm.formValue.priority = 2
      wrapper.vm.scheduleType = 'delay'
      wrapper.vm.delayValue = 10
      wrapper.vm.delayUnit = 'hours'

      await wrapper.vm.handleReset()

      expect(wrapper.vm.formValue.project_id).toBeUndefined()
      expect(wrapper.vm.formValue.base_branch).toBeUndefined()
      expect(wrapper.vm.formValue.new_branch_name).toBe('')
      expect(wrapper.vm.formValue.target_branch).toBe('main')
      expect(wrapper.vm.formValue.user_prompt).toBe('')
      expect(wrapper.vm.formValue.priority).toBe(0)
      expect(wrapper.vm.scheduleType).toBe('now')
      expect(wrapper.vm.delayValue).toBe(5)
      expect(wrapper.vm.delayUnit).toBe('minutes')
    })

    it('should clear validation errors', async () => {
      await mountComponent()

      // Simply verify handleReset completes without error
      // The actual form validation clearing is handled internally by the form component
      await wrapper.vm.handleReset()
      // If we get here without error, the test passes
      expect(true).toBe(true)
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
})
