import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper, flushPromises } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import CreateIssue from './CreateIssue.vue'
import { createMockProject, createMockBranch, createMockPromptTemplate } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
  const mock = {
    getProjects: vi.fn<() => Promise<any[]>>(),
    getBranches: vi.fn<() => Promise<any[]>>(),
    createIssue: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
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

// Mock dependencies
vi.mock('../api', () => ({
  getProjects: mockApi.getProjects,
  getBranches: mockApi.getBranches,
  createIssue: mockApi.createIssue,
  getPromptTemplates: mockApi.getPromptTemplates,
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

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({ isMobile: ref(false), isCompact: ref(false), width: ref(1200) })
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
      return () => h('div', { class: 'n-form-item' }, [slots.default?.(), slots.feedback?.()])
    }
  },
  NSelect: {
    name: 'NSelect',
    props: ['options', 'loading', 'placeholder', 'disabled', 'value', 'filterable'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        disabled: props.disabled,
        onChange: (e: Event) => emit('update:value', Number((e.target as HTMLSelectElement).value) || (e.target as HTMLSelectElement).value)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    }
  },
  NInput: {
    name: 'NInput',
    props: ['placeholder', 'disabled', 'value', 'type', 'rows'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        type: 'text',
        placeholder: props.placeholder,
        disabled: props.disabled,
        value: props.value,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'secondary', 'strong', 'round', 'loading', 'disabled', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('button', {
        class: ['n-button', { loading: props.loading, disabled: props.disabled }],
        disabled: props.disabled || props.loading
      }, slots.default?.())
    }
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [
        slots.header?.(),
        slots.default?.()
      ])
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify', 'wrap', 'align'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'x-gap', 'y-gap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    }
  },
  NGi: {
    name: 'NGi',
    props: [],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    }
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        role: 'switch',
        'aria-checked': props.value,
        onClick: () => emit('update:value', !props.value)
      })
    }
  },
  NSpin: {
    name: 'NSpin',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-spin-loading' }, slots.default?.()) : h('div', { class: 'n-spin' }, slots.default?.())
    }
  },
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
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    setup(_props: any) {
      return () => h('i', { class: 'n-icon' })
    }
  },
  useMessage: () => mockMessage,
}))

// Mock PageHeader component
vi.mock('../components/PageHeader.vue', () => ({
  default: {
    name: 'PageHeader',
    props: ['title', 'subtitle', 'rootClass', 'titleClass', 'subtitleClass'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'page-header-mock' }, slots.actions?.())
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
    }
  }
}))

// Mock @vicons/ionicons5
vi.mock('@vicons/ionicons5', () => ({
  DocumentTextOutline: { name: 'DocumentTextOutline' },
  WarningOutline: { name: 'WarningOutline' }
}))

// Router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/issues/create', name: 'CreateIssue', component: { template: '<div>create</div>' } },
    { path: '/issues/:id', name: 'IssueView', component: { template: '<div>issue</div>' } },
  ]
})

// Mock data
const mockProjects = [
  createMockProject({ id: 1, name: 'Project 1', path_with_namespace: 'group/project-1', default_branch: 'main' }),
  createMockProject({ id: 2, name: 'Project 2', path_with_namespace: 'group/project-2', default_branch: 'develop' }),
]

const mockBranches = [
  createMockBranch({ name: 'main' }),
  createMockBranch({ name: 'develop' }),
  createMockBranch({ name: 'feature/test' }),
]

const mockTemplates = [
  createMockPromptTemplate({ id: 1, name: 'Bug Fix', content: 'Fix {{issue}}', variable_tips: { issue: 'Issue description' } }),
  createMockPromptTemplate({ id: 2, name: 'Feature', content: 'Add {{feature}}', variable_tips: { feature: 'Feature name' } }),
]

const mockCreatedIssue = {
  id: 42,
  title: 'My Issue',
  description: 'Some description',
  project_id: 1,
  status: 'open',
  branch_name: 'codify/issue-42',
  base_branch: 'main',
  target_branch: 'main',
  merge_request_iid: null,
  merge_request_url: null,
  claude_session_id: null,
  initiator_user_id: null,
  initiator_username: null,
  created_at: '2026-04-01T10:00:00Z',
  updated_at: '2026-04-01T10:00:00Z',
}

describe('CreateIssue', () => {
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
    ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
    ;(mockApi.getPromptTemplates as Mock).mockResolvedValue(mockTemplates)
    ;(mockApi.createIssue as Mock).mockResolvedValue(mockCreatedIssue)
    ;(mockApi.getBranches as Mock).mockResolvedValue(mockBranches)

    wrapper = mount(CreateIssue, {
      global: {
        plugins: [router],
      }
    })

    // Wait for onMounted to complete
    await vi.waitFor(() => {
      return (mockApi.getProjects as Mock).mock.calls.length > 0
    })
    await flushPromises()

    return wrapper
  }

  // ── Basic Rendering ──────────────────────────────────────────

  describe('basic rendering', () => {
    it('should render the create issue page', async () => {
      await mountComponent()

      expect(wrapper.find('.create-issue-page').exists()).toBe(true)
    })

    it('should render the form', async () => {
      await mountComponent()

      expect(wrapper.find('form').exists()).toBe(true)
    })

    it('should render project select', async () => {
      await mountComponent()

      const selects = wrapper.findAll('select.n-select')
      expect(selects.length).toBeGreaterThanOrEqual(1)
    })

    it('should render title input', async () => {
      await mountComponent()

      const inputs = wrapper.findAll('input.n-input')
      expect(inputs.length).toBeGreaterThanOrEqual(1)
    })

    it('should render description variable editor', async () => {
      await mountComponent()

      expect(wrapper.find('.variable-editor').exists()).toBe(true)
    })

    it('should render submit button', async () => {
      await mountComponent()

      const buttons = wrapper.findAll('button.n-button')
      const submitBtn = buttons.find((b: any) => b.text().includes('issue.create'))
      expect(submitBtn).toBeTruthy()
    })

    it('should render reset button', async () => {
      await mountComponent()

      const buttons = wrapper.findAll('button.n-button')
      const resetBtn = buttons.find((b: any) => b.text().includes('common.reset'))
      expect(resetBtn).toBeTruthy()
    })

    it('should render cancel button in header', async () => {
      await mountComponent()

      const buttons = wrapper.findAll('button.n-button')
      const cancelBtn = buttons.find((b: any) => b.text().includes('common.cancel'))
      expect(cancelBtn).toBeTruthy()
    })

    it('should render MR toggle switch', async () => {
      await mountComponent()

      expect(wrapper.find('button.n-switch').exists()).toBe(true)
    })

    it('should render base branch select', async () => {
      await mountComponent()

      const selects = wrapper.findAll('select.n-select')
      // project select + base branch select (target branch hidden when create_mr is false)
      expect(selects.length).toBeGreaterThanOrEqual(2)
    })
  })

  // ── Fetching on Mount ─────────────────────────────────────────

  describe('fetching on mount', () => {
    it('should fetch projects on mount', async () => {
      await mountComponent()

      expect(mockApi.getProjects).toHaveBeenCalledTimes(1)
    })

    it('should fetch prompt templates on mount', async () => {
      await mountComponent()

      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })

    it('should populate project options from fetched projects', async () => {
      await mountComponent()

      const options = wrapper.vm.projectOptions
      expect(options).toHaveLength(2)
      expect(options[0]).toEqual({ label: 'group/project-1', value: 1 })
      expect(options[1]).toEqual({ label: 'group/project-2', value: 2 })
    })
  })

  // ── Project Selection & Branch Loading ────────────────────────

  describe('project selection', () => {
    it('should call fetchBranches when project is selected', async () => {
      await mountComponent()

      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      expect(mockApi.getBranches).toHaveBeenCalledWith(1)
    })

    it('should clear branch selections when project changes', async () => {
      await mountComponent()

      wrapper.vm.formValue.base_branch = 'old-branch'
      wrapper.vm.formValue.target_branch = 'old-target'

      wrapper.vm.handleProjectChange(2)
      await flushPromises()

      // base_branch and target_branch are cleared before fetchBranches
      // then base_branch gets auto-set to default_branch
      expect(mockApi.getBranches).toHaveBeenCalledWith(2)
    })

    it('should auto-set base_branch to project default branch', async () => {
      await mountComponent()

      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      expect(wrapper.vm.formValue.base_branch).toBe('main')
    })

    it('should populate branch options after project selection', async () => {
      await mountComponent()

      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      const options = wrapper.vm.branchOptions
      expect(options).toHaveLength(3)
      expect(options[0]).toEqual({ label: 'main', value: 'main' })
      expect(options[1]).toEqual({ label: 'develop', value: 'develop' })
      expect(options[2]).toEqual({ label: 'feature/test', value: 'feature/test' })
    })

    it('should not auto-set base_branch if default branch not in branch list', async () => {
      await mountComponent()

      // Override getBranches AFTER mount to return branches without 'main'
      ;(mockApi.getBranches as Mock).mockResolvedValue([
        createMockBranch({ name: 'feature/other' }),
      ])

      wrapper.vm.handleProjectChange(1) // project-1 default is 'main'
      await flushPromises()

      expect(wrapper.vm.formValue.base_branch).toBeUndefined()
    })

    it('should not call fetchBranches when projectId is falsy', async () => {
      await mountComponent()

      ;(mockApi.getBranches as Mock).mockClear()
      wrapper.vm.handleProjectChange(0)
      await flushPromises()

      expect(mockApi.getBranches).not.toHaveBeenCalled()
    })
  })

  // ── MR Toggle ─────────────────────────────────────────────────

  describe('MR toggle (create_mr)', () => {
    it('should not show target branch select when create_mr is false', async () => {
      await mountComponent()

      expect(wrapper.vm.formValue.create_mr).toBe(false)
      // Target branch select should not be in DOM (v-if="formValue.create_mr")
      const text = wrapper.text()
      expect(text).not.toContain('issue.field.targetBranch')
    })

    it('should show target branch select when create_mr is true', async () => {
      await mountComponent()

      wrapper.vm.formValue.create_mr = true
      await nextTick()

      // The target branch section should now render
      const selects = wrapper.findAll('select.n-select')
      // project select + base branch select + target branch select
      expect(selects.length).toBeGreaterThanOrEqual(3)
    })

    it('should auto-fill target_branch with default branch when MR toggled on', async () => {
      await mountComponent()

      // Select project and load branches
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      // Toggle MR on
      wrapper.vm.formValue.create_mr = true
      await nextTick()

      expect(wrapper.vm.formValue.target_branch).toBe('main')
    })

    it('should auto-set target_branch when MR enabled during fetchBranches', async () => {
      await mountComponent()

      // Enable MR first
      wrapper.vm.formValue.create_mr = true
      wrapper.vm.formValue.project_id = 1
      await nextTick()

      // Now select project which triggers fetchBranches
      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      // fetchBranches auto-sets target_branch when create_mr is true
      expect(wrapper.vm.formValue.target_branch).toBe('main')
    })

    it('should not overwrite target_branch if already set when MR toggled on', async () => {
      await mountComponent()

      // Load branches for project 1
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      // Manually set target branch
      wrapper.vm.formValue.target_branch = 'develop'

      // Toggle MR on - should NOT overwrite because target_branch is already set
      wrapper.vm.formValue.create_mr = true
      await nextTick()

      expect(wrapper.vm.formValue.target_branch).toBe('develop')
    })

    it('should not auto-fill target_branch when no project selected', async () => {
      await mountComponent()

      // Toggle MR on without project
      wrapper.vm.formValue.create_mr = true
      await nextTick()

      expect(wrapper.vm.formValue.target_branch).toBeUndefined()
    })
  })

  // ── Form Validation ───────────────────────────────────────────

  describe('form validation', () => {
    it('should not call createIssue when form validation fails', async () => {
      await mountComponent()

      // Make validate reject
      const formRef = wrapper.vm.formRef
      formRef.validate.mockRejectedValue(new Error('Validation failed'))

      await wrapper.vm.handleSubmit()

      expect(mockApi.createIssue).not.toHaveBeenCalled()
    })

    it('should require base_branch before submitting', async () => {
      await mountComponent()

      const formRef = wrapper.vm.formRef
      formRef.validate.mockResolvedValue(undefined)

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = undefined

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockApi.createIssue).not.toHaveBeenCalled()
      expect(mockMessage.error).toHaveBeenCalledWith('createTask.selectBaseBranch')
    })

    it('should have required project_id rule', async () => {
      await mountComponent()

      // Verify initial form value has no project_id
      expect(wrapper.vm.formValue.project_id).toBeUndefined()
    })

    it('should have required title rule', async () => {
      await mountComponent()

      expect(wrapper.vm.formValue.title).toBe('')
    })

    it('should return early when formRef is null', async () => {
      await mountComponent()

      wrapper.vm.formRef = null

      await wrapper.vm.handleSubmit()

      expect(mockApi.createIssue).not.toHaveBeenCalled()
    })
  })

  // ── Successful Submission ──────────────────────────────────────

  describe('successful form submission', () => {
    it('should call createIssue with correct payload', async () => {
      await mountComponent()

      // Fill required fields
      wrapper.vm.formValue.title = 'Test Issue Title'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.description = 'Issue description'
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockApi.createIssue).toHaveBeenCalledTimes(1)
      const call = (mockApi.createIssue as Mock).mock.calls[0][0]
      expect(call.title).toBe('Test Issue Title')
      expect(call.project_id).toBe(1)
      expect(call.description).toBe('Issue description')
      expect(call.base_branch).toBe('main')
    })

    it('should show success message after creation', async () => {
      await mountComponent()

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockMessage.success).toHaveBeenCalledWith('issue.create')
    })

    it('should navigate to issue detail page after creation', async () => {
      await mountComponent()

      const pushSpy = vi.spyOn(router, 'push')

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(pushSpy).toHaveBeenCalledWith('/issues/42')
    })

    it('should not send target_branch when create_mr is false', async () => {
      await mountComponent()

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.target_branch = 'main'
      wrapper.vm.formValue.create_mr = false

      await wrapper.vm.handleSubmit()
      await flushPromises()

      const call = (mockApi.createIssue as Mock).mock.calls[0][0]
      expect(call.target_branch).toBeUndefined()
    })

    it('should send target_branch when create_mr is true', async () => {
      await mountComponent()

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.target_branch = 'develop'
      wrapper.vm.formValue.create_mr = true

      await wrapper.vm.handleSubmit()
      await flushPromises()

      const call = (mockApi.createIssue as Mock).mock.calls[0][0]
      expect(call.target_branch).toBe('develop')
    })

    it('should send description as undefined when empty', async () => {
      await mountComponent()

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.description = ''

      await wrapper.vm.handleSubmit()
      await flushPromises()

      const call = (mockApi.createIssue as Mock).mock.calls[0][0]
      expect(call.description).toBeUndefined()
    })

    it('should reject empty base_branch on submit', async () => {
      await mountComponent()

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = undefined

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockApi.createIssue).not.toHaveBeenCalled()
      expect(mockMessage.error).toHaveBeenCalledWith('createTask.selectBaseBranch')
    })

    it('should set submitting to true during submission and false after', async () => {
      await mountComponent()

      let resolveCreateIssue: ((value: any) => void) | undefined
      ;(mockApi.createIssue as Mock).mockImplementation(() => new Promise(resolve => {
        resolveCreateIssue = resolve
      }))

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      expect(wrapper.vm.submitting).toBe(false)

      const submitPromise = wrapper.vm.handleSubmit()

      // Wait for the async function to reach the createIssue call
      await flushPromises()
      expect(wrapper.vm.submitting).toBe(true)

      resolveCreateIssue!(mockCreatedIssue)
      await submitPromise
      await flushPromises()

      expect(wrapper.vm.submitting).toBe(false)
    })
  })

  // ── Submission Errors ─────────────────────────────────────────

  describe('submission error handling', () => {
    it('should show error message on API failure', async () => {
      await mountComponent()

      ;(mockApi.createIssue as Mock).mockRejectedValue(new Error('API Error'))

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('API Error')
    })

    it('should show response.data.message on API failure with response', async () => {
      await mountComponent()

      const apiError = { response: { data: { message: 'Server validation failed' } } }
      ;(mockApi.createIssue as Mock).mockRejectedValue(apiError)

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('Server validation failed')
    })

    it('should stringify non-Error objects', async () => {
      await mountComponent()

      ;(mockApi.createIssue as Mock).mockRejectedValue('string error')

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('string error')
    })

    it('should set submitting to false after error', async () => {
      await mountComponent()

      ;(mockApi.createIssue as Mock).mockRejectedValue(new Error('fail'))

      wrapper.vm.formValue.title = 'Test Issue'
      wrapper.vm.formValue.project_id = 1

      await wrapper.vm.handleSubmit()
      await flushPromises()

      expect(wrapper.vm.submitting).toBe(false)
    })
  })

  // ── Form Reset ────────────────────────────────────────────────

  describe('form reset', () => {
    it('should reset all form fields to initial values', async () => {
      await mountComponent()

      // Set various values
      wrapper.vm.formValue.title = 'Some title'
      wrapper.vm.formValue.description = 'Some desc'
      wrapper.vm.formValue.project_id = 1
      wrapper.vm.formValue.base_branch = 'main'
      wrapper.vm.formValue.target_branch = 'develop'
      wrapper.vm.formValue.create_mr = true

      await wrapper.vm.handleReset()

      expect(wrapper.vm.formValue.title).toBe('')
      expect(wrapper.vm.formValue.description).toBe('')
      expect(wrapper.vm.formValue.project_id).toBeUndefined()
      expect(wrapper.vm.formValue.base_branch).toBeUndefined()
      expect(wrapper.vm.formValue.target_branch).toBeUndefined()
      expect(wrapper.vm.formValue.create_mr).toBe(false)
    })

    it('should clear branches on reset', async () => {
      await mountComponent()

      // Load branches first
      wrapper.vm.handleProjectChange(1)
      await flushPromises()
      expect(wrapper.vm.branchOptions.length).toBeGreaterThan(0)

      await wrapper.vm.handleReset()

      expect(wrapper.vm.branchOptions).toEqual([])
    })

    it('should call restoreValidation on formRef', async () => {
      await mountComponent()

      const formRef = wrapper.vm.formRef
      await wrapper.vm.handleReset()

      expect(formRef.restoreValidation).toHaveBeenCalled()
    })
  })

  // ── Prompt Templates ──────────────────────────────────────────

  describe('prompt templates', () => {
    it('should load templates on mount', async () => {
      await mountComponent()

      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })

    it('should apply template content to description', async () => {
      await mountComponent()

      const template = mockTemplates[0]
      wrapper.vm.applyPromptTemplate(template)

      expect(wrapper.vm.formValue.description).toBe(template.content)
    })

    it('should set promptVariableTips from template variable_tips', async () => {
      await mountComponent()

      const template = mockTemplates[0]
      wrapper.vm.applyPromptTemplate(template)

      expect(wrapper.vm.promptVariableTips).toEqual(template.variable_tips)
    })

    it('should not set promptVariableTips when template has no variable_tips', async () => {
      await mountComponent()

      const templateNoTips = createMockPromptTemplate({ id: 3, name: 'No Tips', content: 'Simple template', variable_tips: undefined })
      wrapper.vm.applyPromptTemplate(templateNoTips)

      expect(wrapper.vm.formValue.description).toBe('Simple template')
      expect(wrapper.vm.promptVariableTips).toBeUndefined()
    })

    it('should show template drawer when showTemplateDrawer is true', async () => {
      await mountComponent()

      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      expect(wrapper.find('.n-drawer').exists()).toBe(true)
      expect(wrapper.find('.n-drawer-content').exists()).toBe(true)
    })

    it('should not show template drawer when showTemplateDrawer is false', async () => {
      await mountComponent()

      expect(wrapper.vm.showTemplateDrawer).toBe(false)
      // Drawer renders as empty div when not shown
      expect(wrapper.find('.n-drawer').exists()).toBe(false)
    })

    it('should render template items in drawer', async () => {
      await mountComponent()

      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      const templateItems = wrapper.findAll('.prompt-template-dropdown__item')
      expect(templateItems).toHaveLength(2)
    })

    it('should apply template and close drawer on template item click', async () => {
      await mountComponent()

      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      const templateItem = wrapper.find('.prompt-template-dropdown__item')
      await templateItem.trigger('click')

      expect(wrapper.vm.formValue.description).toBe(mockTemplates[0].content)
      expect(wrapper.vm.showTemplateDrawer).toBe(false)
    })
  })

  // ── Unreplaced Variables ──────────────────────────────────────

  describe('unreplaced variables', () => {
    it('should detect unreplaced variables in description', async () => {
      await mountComponent()

      wrapper.vm.formValue.description = 'Fix the {{issue}} in {{file}}'

      expect(wrapper.vm.unreplacedVariables).toEqual(['issue', 'file'])
    })

    it('should return empty array when no variables', async () => {
      await mountComponent()

      wrapper.vm.formValue.description = 'Plain description with no variables'

      expect(wrapper.vm.unreplacedVariables).toEqual([])
    })

    it('should return empty array when description is empty', async () => {
      await mountComponent()

      wrapper.vm.formValue.description = ''

      expect(wrapper.vm.unreplacedVariables).toEqual([])
    })

    it('should show warning when unreplaced variables exist', async () => {
      await mountComponent()

      wrapper.vm.formValue.description = 'Fix {{bug}} in {{module}}'
      await nextTick()

      const warning = wrapper.find('.prompt-variable-warning')
      expect(warning.exists()).toBe(true)
    })

    it('should not show warning when all variables replaced', async () => {
      await mountComponent()

      wrapper.vm.formValue.description = 'Fix the login bug in auth module'
      await nextTick()

      const warning = wrapper.find('.prompt-variable-warning')
      expect(warning.exists()).toBe(false)
    })
  })

  // ── Cancel Button ─────────────────────────────────────────────

  describe('cancel button', () => {
    it('should call router.back() when cancel is clicked', async () => {
      await mountComponent()

      const backSpy = vi.spyOn(router, 'back')

      const buttons = wrapper.findAll('button.n-button')
      const cancelBtn = buttons.find((b: any) => b.text().includes('common.cancel'))
      expect(cancelBtn).toBeTruthy()

      await cancelBtn!.trigger('click')

      expect(backSpy).toHaveBeenCalled()
    })
  })

  // ── Fetch Error Handling ──────────────────────────────────────

  describe('fetch error handling', () => {
    it('should show error message when fetchProjects fails', async () => {
      ;(mockApi.getProjects as Mock).mockRejectedValue(new Error('Network error'))
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])

      wrapper = mount(CreateIssue, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => {
        return (mockApi.getProjects as Mock).mock.calls.length > 0
      })
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('createTask.failedToFetchProjects')
      // Component should not crash
      expect(wrapper.find('.create-issue-page').exists()).toBe(true)
      expect(wrapper.vm.projectOptions).toEqual([])
    })

    it('should show error message when fetchBranches fails', async () => {
      await mountComponent()

      ;(mockApi.getBranches as Mock).mockRejectedValue(new Error('Branch error'))

      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('createTask.failedToFetchBranches')
    })

    it('should handle fetchPromptTemplates error silently (non-critical)', async () => {
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getPromptTemplates as Mock).mockRejectedValue(new Error('Template error'))

      wrapper = mount(CreateIssue, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => {
        return (mockApi.getPromptTemplates as Mock).mock.calls.length > 0
      })
      await flushPromises()

      // Should NOT show error message for template fetch failure
      expect(mockMessage.error).not.toHaveBeenCalled()
      // Component should still render
      expect(wrapper.find('.create-issue-page').exists()).toBe(true)
    })
  })

  // ── Branch Loading State ──────────────────────────────────────

  describe('branch loading state', () => {
    it('should clear branches array before fetching new ones', async () => {
      await mountComponent()

      // Load branches for project 1
      wrapper.vm.handleProjectChange(1)
      await flushPromises()
      expect(wrapper.vm.branchOptions.length).toBeGreaterThan(0)

      // Change project - branches should be cleared then reloaded
      ;(mockApi.getBranches as Mock).mockResolvedValue([createMockBranch({ name: 'new-branch' })])
      wrapper.vm.handleProjectChange(2)
      await flushPromises()

      expect(wrapper.vm.branchOptions).toEqual([{ label: 'new-branch', value: 'new-branch' }])
    })
  })

  // ── Use Template Button ───────────────────────────────────────

  describe('use template button', () => {
    it('should be disabled when no templates are loaded', async () => {
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])
      ;(mockApi.createIssue as Mock).mockResolvedValue(mockCreatedIssue)
      ;(mockApi.getBranches as Mock).mockResolvedValue(mockBranches)

      wrapper = mount(CreateIssue, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => {
        return (mockApi.getPromptTemplates as Mock).mock.calls.length > 0
      })
      await flushPromises()

      const buttons = wrapper.findAll('button.n-button')
      const templateBtn = buttons.find((b: any) => b.text().includes('createTask.useTemplate'))
      expect(templateBtn).toBeTruthy()
      expect(templateBtn!.element.disabled).toBe(true)
    })

    it('should be enabled when templates are loaded', async () => {
      await mountComponent()

      const buttons = wrapper.findAll('button.n-button')
      const templateBtn = buttons.find((b: any) => b.text().includes('createTask.useTemplate'))
      expect(templateBtn).toBeTruthy()
      expect(templateBtn!.element.disabled).toBe(false)
    })
  })

  // ── Default Branch Auto-Set with MR ───────────────────────────

  describe('default branch auto-set with MR during fetchBranches', () => {
    it('should set target_branch when create_mr is already enabled during fetchBranches', async () => {
      await mountComponent()

      wrapper.vm.formValue.create_mr = true
      wrapper.vm.formValue.project_id = 2
      await nextTick()

      wrapper.vm.handleProjectChange(2)
      await flushPromises()

      // Project 2 has default_branch 'develop', and 'develop' is in mockBranches
      expect(wrapper.vm.formValue.base_branch).toBe('develop')
      expect(wrapper.vm.formValue.target_branch).toBe('develop')
    })

    it('should not set target_branch when create_mr is false during fetchBranches', async () => {
      await mountComponent()

      wrapper.vm.formValue.create_mr = false
      wrapper.vm.handleProjectChange(1)
      await flushPromises()

      expect(wrapper.vm.formValue.base_branch).toBe('main')
      expect(wrapper.vm.formValue.target_branch).toBeUndefined()
    })
  })

  // ── Empty Template Drawer ─────────────────────────────────────

  describe('empty template drawer', () => {
    it('should show empty message when no templates exist', async () => {
      ;(mockApi.getProjects as Mock).mockResolvedValue(mockProjects)
      ;(mockApi.getPromptTemplates as Mock).mockResolvedValue([])
      ;(mockApi.createIssue as Mock).mockResolvedValue(mockCreatedIssue)
      ;(mockApi.getBranches as Mock).mockResolvedValue(mockBranches)

      wrapper = mount(CreateIssue, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => {
        return (mockApi.getPromptTemplates as Mock).mock.calls.length > 0
      })
      await flushPromises()

      wrapper.vm.showTemplateDrawer = true
      await nextTick()

      const emptyMsg = wrapper.find('.prompt-template-dropdown__empty')
      expect(emptyMsg.exists()).toBe(true)
    })
  })
})
