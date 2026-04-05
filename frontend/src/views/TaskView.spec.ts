import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import TaskView from './TaskView.vue'
import { createMockTask, createMockTaskLog } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi } = vi.hoisted(() => {
  const mock = {
    getTask: vi.fn<() => Promise<any>>(),
    getTaskLogs: vi.fn<() => Promise<any[]>>(),
    getTaskContainerLogs: vi.fn<() => Promise<any>>(),
    getTaskStats: vi.fn<() => Promise<any>>(),
    cancelTask: vi.fn<() => Promise<void>>(),
    retryTask: vi.fn<() => Promise<void>>(),
    executeTask: vi.fn<() => Promise<void>>(),
    rescheduleTask: vi.fn<() => Promise<any>>(),
    getAuthStatus: vi.fn<() => Promise<any>>(),
    streamTaskLogs: vi.fn<() => any>()
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

// Mock i18n module
vi.mock('../i18n', () => ({
  currentLocale: ref('en')
}))

// Mock datetime utils
vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8: vi.fn((value: any) => `formatted-date-${value}`),
  parseUtcDate: vi.fn((value: any) => {
    if (!value) return new Date(0)
    return new Date(value)
  })
}))

// Mock auth module
vi.mock('../auth', () => ({
  authState: {
    oidcEnabled: false,
    user: null,
    initialized: true
  },
  isAdmin: ref(false),
  initializeAuth: vi.fn<() => Promise<any>>()
}))

// Mock dependencies
vi.mock('../api', () => ({
  getTask: mockApi.getTask,
  getTaskLogs: mockApi.getTaskLogs,
  getTaskContainerLogs: mockApi.getTaskContainerLogs,
  getTaskStats: mockApi.getTaskStats,
  cancelTask: mockApi.cancelTask,
  retryTask: mockApi.retryTask,
  executeTask: mockApi.executeTask,
  rescheduleTask: mockApi.rescheduleTask,
  getAuthStatus: mockApi.getAuthStatus,
  streamTaskLogs: mockApi.streamTaskLogs
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

// Mock EventSource - create once, reuse
const mockEventSourceInstance = {
  onmessage: null as ((event: any) => void) | null,
  onerror: null as (() => void) | null,
  close: vi.fn()
}
vi.stubGlobal('EventSource', vi.fn(() => mockEventSourceInstance))

// Mock naive-ui components
vi.mock('naive-ui', () => ({
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'label-placement'],
    setup(_props: any, { expose }: any) {
      expose({ validate: vi.fn(), restoreValidation: vi.fn() })
      return () => h('form', {}, h('div', {}, 'form content'))
    },
    template: '<form><slot /></form>'
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
    props: ['value', 'type', 'placeholder', 'is-date-disabled', 'disabled'],
    setup(props: any) {
      return () => h('div', {
        class: 'n-date-picker',
        'data-value': props.value
      }, props.placeholder)
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
        class: ['n-button', `n-button--${props.type || 'default'}`, { loading: props.loading, disabled: props.disabled }],
        disabled: props.disabled || props.loading,
        'data-type': props.type
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
  NSpin: {
    name: 'NSpin',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-spin-loading' }, slots.default?.()) : h('div', { class: 'n-spin' }, slots.default?.())
    },
    template: '<div class="n-spin"><slot /></div>'
  },
  NAlert: {
    name: 'NAlert',
    props: ['type'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: ['n-alert', `n-alert--${props.type}`] }, slots.default?.())
    },
    template: '<div class="n-alert"><slot /></div>'
  },
  NText: {
    name: 'NText',
    setup(_props: any, { slots }: any) {
      return () => h('span', { class: 'n-text' }, slots.default?.())
    },
    template: '<span class="n-text"><slot /></span>'
  },
  NDescriptions: {
    name: 'NDescriptions',
    props: ['column', 'label-placement'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-descriptions' }, slots.default?.())
    },
    template: '<div class="n-descriptions"><slot /></div>'
  },
  NDescriptionsItem: {
    name: 'NDescriptionsItem',
    props: ['label'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: 'n-descriptions-item' }, [
        h('span', { class: 'n-descriptions-item__label' }, props.label),
        h('span', { class: 'n-descriptions-item__content' }, slots.default?.())
      ])
    },
    template: '<div class="n-descriptions-item"><slot /></div>'
  },
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }),
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'size'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tabs' }, slots.default?.())
    }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab', 'disabled'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tab-pane' }, slots.default?.())
    }
  },
  NCollapse: {
    name: 'NCollapse',
    props: ['default-expanded-names'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-collapse' }, slots.default?.())
    }
  },
  NCollapseItem: {
    name: 'NCollapseItem',
    props: ['title', 'name'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-collapse-item' }, slots.default?.())
    }
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description'],
    setup(props: any) {
      return () => h('div', { class: 'n-empty' }, props.description)
    }
  }
}))

// Mock @vicons/ionicons5
vi.mock('@vicons/ionicons5', () => ({
  PersonOutline: { name: 'PersonOutline' },
  LogoGitlab: { name: 'LogoGitlab' },
  FolderOpenOutline: { name: 'FolderOpenOutline' },
  GitMergeOutline: { name: 'GitMergeOutline' },
  GitBranchOutline: { name: 'GitBranchOutline' },
  ChatbubbleOutline: { name: 'ChatbubbleOutline' },
  TimeOutline: { name: 'TimeOutline' },
  GitPullRequest: { name: 'GitPullRequest' },
  CubeOutline: { name: 'CubeOutline' },
  ArrowDownCircleOutline: { name: 'ArrowDownCircleOutline' },
  AlertCircleOutline: { name: 'AlertCircleOutline' },
  CodeOutline: { name: 'CodeOutline' },
  TerminalOutline: { name: 'TerminalOutline' },
  CheckmarkCircleOutline: { name: 'CheckmarkCircleOutline' },
  CloseCircleOutline: { name: 'CloseCircleOutline' },
  DocumentTextOutline: { name: 'DocumentTextOutline' },
  CreateOutline: { name: 'CreateOutline' },
  BulbOutline: { name: 'BulbOutline' },
  SearchOutline: { name: 'SearchOutline' }
}))

// Mock ansi-to-html
vi.mock('ansi-to-html', () => ({
  default: vi.fn().mockImplementation(() => ({
    toHtml: vi.fn((text: string) => `<span>${text}</span>`)
  }))
}))

// Mock router
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'home', component: { template: '<div>home</div>' } },
    { path: '/tasks/:id', name: 'task-view', component: TaskView }
  ]
})

describe('TaskView', () => {
  let wrapper: VueWrapper<any>

  const createMockTaskWithStatus = (status: string, overrides = {}) => {
    return createMockTask({
      id: 1,
      status,
      initiator_user_id: 1,
      initiator_gitlab_user_id: 10,
      initiator_username: 'testuser',
      project_path_with_namespace: 'group/test-project',
      project_url: 'https://gitlab.example.com/group/test-project',
      issue_iid: 42,
      issue_url: 'https://gitlab.example.com/group/test-project/-/issues/42',
      branch_name: 'fix-login-bug',
      branch_url: 'https://gitlab.example.com/group/test-project/-/tree/fix-login-bug',
      target_branch: 'main',
      priority: 1,
      user_prompt: 'Fix the login bug',
      is_manual: true,
      created_at: '2026-03-31T10:00:00Z',
      scheduled_at: null,
      container_id: status === 'running' ? 'container-123' : null,
      ...overrides
    })
  }

  beforeEach(async () => {
    vi.clearAllMocks()
    resetMockApi()
    mockEventSourceInstance.close.mockClear()
    mockEventSourceInstance.onerror = null
    ;(mockApi.streamTaskLogs as Mock).mockReturnValue(mockEventSourceInstance)
    router.push('/tasks/1')
    await router.isReady()
    vi.useFakeTimers()
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
    }
    vi.useRealTimers()
  })

  const mountComponent = async (taskOverrides = {}) => {
    const mockTask = createMockTaskWithStatus('pending', taskOverrides)
    ;(mockApi.getTask as Mock).mockResolvedValue(mockTask)
    ;(mockApi.getTaskLogs as Mock).mockResolvedValue([
      createMockTaskLog({ task_id: 1, message: 'Log entry 1', log_level: 'info' }),
      createMockTaskLog({ task_id: 1, message: 'Log entry 2', log_level: 'info' })
    ])
    ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({
      container_id: 'container-123',
      container_status: 'running',
      logs: 'Container log content',
      status: 'running'
    })

    wrapper = mount(TaskView, {
      global: {
        plugins: [router]
      }
    })

    // Wait for onMounted to complete
    await vi.waitFor(() => {
      return (mockApi.getTask as Mock).mock.calls.length > 0
    })

    await nextTick()

    return wrapper
  }

  describe('basic rendering', () => {
    it('should render task details', async () => {
      await mountComponent()

      expect(wrapper.find('.task-view').exists()).toBe(true)
      expect(wrapper.find('.task-view__title').exists()).toBe(true)
    })

    it('should fetch task on mount', async () => {
      await mountComponent()

      expect(mockApi.getTask).toHaveBeenCalledWith(1)
    })

    it('should display summary cards', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return wrapper.find('[data-testid="task-actions-card"]').exists()
      })

      // New layout: TaskMetadataPanel + actions card in top row, TaskProcessPanel below
      expect(wrapper.find('.task-metadata-panel').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-actions-card"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-actions"]').exists()).toBe(true)
    })

    it('should display error message for failed tasks', async () => {
      await mountComponent({
        status: 'failed',
        error_message: 'Task failed due to network error'
      })

      await vi.waitFor(() => {
        return wrapper.find('.error-message').exists()
      })

      expect(wrapper.find('.error-message').text()).toContain('Task failed due to network error')
    })
  })

  describe('task actions', () => {
    it('should show cancel button for active tasks', async () => {
      await mountComponent({ status: 'running' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      // Check that cancel button should be visible (actionLoading should be false)
      expect(wrapper.vm.actionLoading).toBe(false)
      // hasActions should be true for running tasks
      expect(wrapper.vm.hasActions).toBe(true)
    })

    it('should show retry button for failed tasks', async () => {
      await mountComponent({ status: 'failed' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      // hasActions should be true for failed tasks
      expect(wrapper.vm.hasActions).toBe(true)
    })

    it('should show execute button for pending tasks', async () => {
      await mountComponent({ status: 'pending' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      // hasActions should be true for pending tasks
      expect(wrapper.vm.hasActions).toBe(true)
    })

    it('should show reschedule controls for scheduled pending tasks', async () => {
      await mountComponent({
        status: 'pending',
        scheduled_at: '2026-04-01T10:00:00Z'
      })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      // canReschedule should be true when task is pending with scheduled_at
      expect(wrapper.vm.canReschedule).toBe(true)
    })

    it('should disable actions based on permissions when not allowed', async () => {
      // Mock OIDC enabled but user is not admin and not the task initiator
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 999, gitlab_user_id: 999, username: 'user-999', display_name: null, email: null, avatar_url: null, platform_role: 'user' }

      await mountComponent({ status: 'pending', initiator_user_id: 1 })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      // canManageTask should be false for non-admin non-initiator
      expect(wrapper.vm.canManageTask).toBe(false)
    })
  })

  describe('action handlers', () => {
    it('should call cancelTask API on cancel', async () => {
      await mountComponent({ status: 'running' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      ;(mockApi.cancelTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('cancelled'))

      // Call handleCancel directly
      await wrapper.vm.handleCancel()

      await vi.waitFor(() => {
        return (mockApi.cancelTask as Mock).mock.calls.length > 0
      })

      expect(mockApi.cancelTask).toHaveBeenCalledWith(1)
    })

    it('should call retryTask API on retry', async () => {
      await mountComponent({ status: 'failed' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      ;(mockApi.retryTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('pending'))

      // Call handleRetry directly
      await wrapper.vm.handleRetry()

      await vi.waitFor(() => {
        return (mockApi.retryTask as Mock).mock.calls.length > 0
      })

      expect(mockApi.retryTask).toHaveBeenCalledWith(1)
    })

    it('should call executeTask API on execute', async () => {
      await mountComponent({ status: 'pending' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      ;(mockApi.executeTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('queued'))

      // Call handleExecute directly
      await wrapper.vm.handleExecute()

      await vi.waitFor(() => {
        return (mockApi.executeTask as Mock).mock.calls.length > 0
      })

      expect(mockApi.executeTask).toHaveBeenCalledWith(1)
    })

    it('should call rescheduleTask API on reschedule', async () => {
      await mountComponent({
        status: 'pending',
        scheduled_at: new Date(Date.now() + 60 * 60 * 1000).toISOString()
      })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const futureTimestamp = Date.now() + 24 * 60 * 60 * 1000
      const futureIso = new Date(futureTimestamp).toISOString()
      ;(mockApi.rescheduleTask as Mock).mockResolvedValue(
        createMockTaskWithStatus('pending', { scheduled_at: futureIso })
      )

      // Set the reschedule datetime
      wrapper.vm.rescheduleDatetime = futureTimestamp

      // Call handleReschedule directly
      await wrapper.vm.handleReschedule()

      await vi.waitFor(() => {
        return (mockApi.rescheduleTask as Mock).mock.calls.length > 0
      })

      expect(mockApi.rescheduleTask).toHaveBeenCalled()
    })

    it('should call retryTask API with schedule on retry with schedule', async () => {
      await mountComponent({ status: 'failed' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const futureTimestamp = Date.now() + 24 * 60 * 60 * 1000
      const futureDate = new Date(futureTimestamp).toISOString()
      ;(mockApi.retryTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('pending'))

      // Set the retry schedule datetime
      wrapper.vm.retryScheduleDatetime = futureTimestamp

      // Call handleRetryWithSchedule directly
      await wrapper.vm.handleRetryWithSchedule()

      await vi.waitFor(() => {
        return (mockApi.retryTask as Mock).mock.calls.length > 0
      })

      expect(mockApi.retryTask).toHaveBeenCalledWith(1, futureDate)
    })

    it('should refresh task after action', async () => {
      await mountComponent({ status: 'running' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const initialFetchCount = (mockApi.getTask as Mock).mock.calls.length
      ;(mockApi.cancelTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('cancelled'))

      // Call handleCancel directly
      await wrapper.vm.handleCancel()

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > initialFetchCount
      })

      // Should have fetched task again after cancel
      expect((mockApi.getTask as Mock).mock.calls.length).toBeGreaterThan(initialFetchCount)
    })
  })

  describe('logs', () => {
    it('should fetch task logs on mount', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })

      expect(mockApi.getTaskLogs).toHaveBeenCalledWith(1)
    })

    it('should display logs with ANSI to HTML conversion', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })

      await vi.waitFor(() => {
        return wrapper.find('.log-content').exists()
      })

      expect(wrapper.find('.log-content').exists()).toBe(true)
    })

    it('should trim large log buffers', async () => {
      await mountComponent()

      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })

      // Access the trimLogBuffer function
      const largeLog = 'x'.repeat(300_000)
      const trimmed = wrapper.vm.trimLogBuffer(largeLog)

      expect(trimmed.length).toBe(200_000)
    })

    it('should display task logs for completed tasks', async () => {
      await mountComponent({ status: 'completed' })

      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })

      await vi.waitFor(() => {
        return wrapper.find('.log-content').exists()
      })

      const logContent = wrapper.find('.log-content')
      expect(logContent.exists()).toBe(true)
    })
  })

  describe('auto-refresh', () => {
    it('should poll every 5 seconds for active tasks', async () => {
      await mountComponent({ status: 'running' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const initialFetchCount = (mockApi.getTask as Mock).mock.calls.length

      // Advance timer by 5 seconds
      await vi.advanceTimersByTimeAsync(5000)

      await nextTick()

      expect((mockApi.getTask as Mock).mock.calls.length).toBe(initialFetchCount + 1)
    })

    it('should not poll when tab is not visible', async () => {
      await mountComponent({ status: 'running' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      // Simulate tab not visible
      Object.defineProperty(document, 'visibilityState', {
        value: 'hidden',
        configurable: true
      })
      document.dispatchEvent(new Event('visibilitychange'))

      const initialFetchCount = (mockApi.getTask as Mock).mock.calls.length

      // Advance timer by 5 seconds
      await vi.advanceTimersByTimeAsync(5000)

      await nextTick()

      // Should not have fetched again since tab was hidden
      expect((mockApi.getTask as Mock).mock.calls.length).toBe(initialFetchCount)
    })

    it('should close log stream on unmount', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })

      // Simulate the user opening the raw-log tab which calls connectLogStream()
      // → connectLogStream creates a new EventSource → logEventSource = mockEventSourceInstance
      await wrapper.vm.onRawTabOpen()

      // Verify the EventSource was opened (via the stubbed EventSource constructor)
      expect(mockEventSourceInstance.close).not.toHaveBeenCalled()

      wrapper.unmount()

      // onBeforeUnmount must call closeLogStream() which closes the EventSource
      expect(mockEventSourceInstance.close).toHaveBeenCalled()
    })
  })

  describe('canManageTask', () => {
    it('should return true when oidc is disabled', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = false
      authState.user = null

      await mountComponent({ status: 'pending' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(true)
    })

    it('should return true for admin users', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 999, gitlab_user_id: 999, username: 'admin-999', display_name: null, email: null, avatar_url: null, platform_role: 'platform_admin' }
      ;(isAdmin as unknown as { value: boolean }).value = true

      await mountComponent({ status: 'pending', initiator_user_id: 1 })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(true)
    })

    it('should return true for task initiator by user_id', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 1, gitlab_user_id: 999, username: 'user-1', display_name: null, email: null, avatar_url: null, platform_role: 'user' }
      ;(isAdmin as unknown as { value: boolean }).value = false

      await mountComponent({ status: 'pending', initiator_user_id: 1, initiator_gitlab_user_id: null })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(true)
    })

    it('should return true for task initiator by gitlab_user_id', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 999, gitlab_user_id: 10, username: 'user-10', display_name: null, email: null, avatar_url: null, platform_role: 'user' }
      ;(isAdmin as unknown as { value: boolean }).value = false

      await mountComponent({
        status: 'pending',
        initiator_user_id: null,
        initiator_gitlab_user_id: 10
      })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(true)
    })

    it('should return false for non-admin non-initiator', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 999, gitlab_user_id: 999, username: 'user-999', display_name: null, email: null, avatar_url: null, platform_role: 'user' }
      ;(isAdmin as unknown as { value: boolean }).value = false

      await mountComponent({ status: 'pending', initiator_user_id: 1, initiator_gitlab_user_id: 10 })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(false)
    })

    it('should return false when user is null with oidc enabled', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = null
      ;(isAdmin as unknown as { value: boolean }).value = false

      await mountComponent({ status: 'pending' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      expect(wrapper.vm.canManageTask).toBe(false)
    })
  })

  describe('computed properties', () => {
    it('should compute isTerminal for terminal statuses', async () => {
      await mountComponent({ status: 'completed' })
      expect(wrapper.vm.isTerminal).toBe(true)

      await mountComponent({ status: 'failed' })
      expect(wrapper.vm.isTerminal).toBe(true)
    })

    it('should compute isTerminal for non-terminal statuses', async () => {
      await mountComponent({ status: 'pending' })
      expect(wrapper.vm.isTerminal).toBe(false)

      await mountComponent({ status: 'running' })
      expect(wrapper.vm.isTerminal).toBe(false)

      await mountComponent({ status: 'queued' })
      expect(wrapper.vm.isTerminal).toBe(false)
    })

    it('should disable past dates for scheduling', async () => {
      await mountComponent({ status: 'pending' })

      const yesterday = Date.now() - 24 * 60 * 60 * 1000
      const tomorrow = Date.now() + 24 * 60 * 60 * 1000

      expect(wrapper.vm.isScheduledDateDisabled(yesterday)).toBe(true)
      expect(wrapper.vm.isScheduledDateDisabled(tomorrow)).toBe(false)
    })

    it('should check active task status correctly', async () => {
      await mountComponent()
      expect(wrapper.vm.isActiveTaskStatus('running')).toBe(true)
      expect(wrapper.vm.isActiveTaskStatus('pending')).toBe(true)
      expect(wrapper.vm.isActiveTaskStatus('queued')).toBe(true)
      expect(wrapper.vm.isActiveTaskStatus('completed')).toBe(false)
      expect(wrapper.vm.isActiveTaskStatus('failed')).toBe(false)
      expect(wrapper.vm.isActiveTaskStatus('cancelled')).toBe(false)
    })

    it('should determine hasActions correctly', async () => {
      await mountComponent({ status: 'pending' })
      expect(wrapper.vm.hasActions).toBe(true)

      await mountComponent({ status: 'running' })
      expect(wrapper.vm.hasActions).toBe(true)

      await mountComponent({ status: 'failed' })
      expect(wrapper.vm.hasActions).toBe(true)

      await mountComponent({ status: 'cancelled' })
      expect(wrapper.vm.hasActions).toBe(true)

      await mountComponent({ status: 'completed' })
      expect(wrapper.vm.hasActions).toBe(false)
    })
  })

  describe('refreshTask', () => {
    it('should refresh task and logs', async () => {
      await mountComponent({ status: 'pending' })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const initialFetchCount = (mockApi.getTask as Mock).mock.calls.length

      await wrapper.vm.refreshTask()

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > initialFetchCount
      })

      expect((mockApi.getTask as Mock).mock.calls.length).toBeGreaterThan(initialFetchCount)
    })
  })

  describe('error handling', () => {
    it('should handle getTask error', async () => {
      ;(mockApi.getTask as Mock).mockRejectedValue(new Error('Failed to fetch task'))

      wrapper = mount(TaskView, {
        global: {
          plugins: [router]
        }
      })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      await nextTick()

      // Should not crash - error is handled internally
      expect(wrapper.find('.task-view').exists()).toBe(true)
    })

    it('should handle getTaskLogs error', async () => {
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('pending'))
      ;(mockApi.getTaskLogs as Mock).mockRejectedValue(new Error('Failed to fetch logs'))

      wrapper = mount(TaskView, {
        global: {
          plugins: [router]
        }
      })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      await nextTick()

      // Should not crash - error is handled internally
      expect(wrapper.find('.task-view').exists()).toBe(true)
    })
  })

  describe('date picker validation', () => {
    it('should disable past dates in scheduler', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })

      await vi.waitFor(() => {
        return wrapper.find('.n-date-picker').exists()
      })

      const pastDate = new Date('2020-01-01').getTime()
      expect(wrapper.vm.isScheduledDateDisabled(pastDate)).toBe(true)

      const futureDate = new Date('2030-01-01').getTime()
      expect(wrapper.vm.isScheduledDateDisabled(futureDate)).toBe(false)
    })
  })
})
