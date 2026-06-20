import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper, flushPromises } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import TaskView from './TaskView.vue'
import { createMockTask, createMockTaskLog } from '../test/mocks/api'

// Use hoisted to ensure proper initialization order
const { mockApi, resetMockApi, mockMessage } = vi.hoisted(() => {
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
    streamTaskLogs: vi.fn<() => any>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getConfig: vi.fn<() => Promise<any>>(),
    getIssue: vi.fn<() => Promise<any>>(),
    getTaskArchive: vi.fn<() => Promise<any>>(),
    downloadTaskArchive: vi.fn<() => Promise<any>>()
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
  streamTaskLogs: mockApi.streamTaskLogs,
  getScheduledTasks: mockApi.getScheduledTasks,
  getConfig: mockApi.getConfig,
  getIssue: mockApi.getIssue,
  getTaskArchive: mockApi.getTaskArchive,
  downloadTaskArchive: mockApi.downloadTaskArchive
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

vi.mock('../components/HeatmapChart.vue', () => ({
  default: {
    name: 'HeatmapChart',
    props: ['tasks', 'selectedMs', 'maxPerSlot', 'enforceCapacity'],
    setup() {
      return () => h('div', { class: 'heatmap-chart-mock' })
    }
  }
}))

vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((_error: any, t: any, fallbackKey: string) => t(fallbackKey))
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } }))
}))

// Mock EventSource - create once, reuse
const mockEventSourceListeners: Record<string, ((event: any) => void) | undefined> = {}
const mockEventSourceInstance = {
  onmessage: null as ((event: any) => void) | null,
  onerror: null as (() => void) | null,
  addEventListener: vi.fn((type: string, handler: (event: any) => void) => {
    mockEventSourceListeners[type] = handler
  }),
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
    setup(props: any, { slots, attrs }: any) {
      return () => h('button', {
        ...attrs,
        class: [attrs.class, 'n-button', `n-button--${props.type || 'default'}`, { loading: props.loading, disabled: props.disabled }],
        disabled: props.disabled || props.loading,
        'data-type': props.type
      }, [
        slots.icon?.(),
        slots.default?.()
      ])
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
    props: ['component', 'size'],
    setup(props: any) {
      return () => h('i', {
        class: 'n-icon',
        'data-icon': props.component?.name
      })
    }
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
  useMessage: () => mockMessage,
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'size'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tabs' }, slots.default?.())
    }
  },
  NTab: {
    name: 'NTab',
    props: ['name', 'disabled'],
    setup(_props: any, { slots }: any) {
      return () => h('button', { class: 'n-tab' }, slots.default?.())
    }
  },
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab', 'disabled'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-tab-pane' }, slots.default?.())
    }
  },
  NBadge: {
    name: 'NBadge',
    props: ['value', 'max', 'show-zero'],
    setup(props: any) {
      return () => h('span', { class: 'n-badge' }, String(props.value ?? ''))
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
  NDrawer: {
    name: 'NDrawer',
    props: ['show', 'width', 'placement'],
    setup(props: any, { attrs, slots }: any) {
      return () => props.show
        ? h('div', { ...attrs, class: ['n-drawer', attrs.class] }, slots.default?.())
        : null
    }
  },
  NDrawerContent: {
    name: 'NDrawerContent',
    props: ['title', 'closable'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-drawer-content' }, slots.default?.())
    }
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description'],
    setup(props: any) {
      return () => h('div', { class: 'n-empty' }, props.description)
    }
  },
  NScrollbar: {
    name: 'NScrollbar',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-scrollbar' }, slots.default?.())
    }
  },
  NModal: {
    name: 'NModal',
    props: ['show', 'preset', 'title'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-modal' }, slots.default?.())
    }
  },
}))

// Mock @vicons/ionicons5
vi.mock('@vicons/ionicons5', () => {
  const icon = (name: string) => ({ name, render: () => null })
  return {
    AlertCircleOutline: icon('AlertCircleOutline'),
    AddCircleOutline: icon('AddCircleOutline'),
    ArrowDownCircleOutline: icon('ArrowDownCircleOutline'),
    ArrowBackOutline: icon('ArrowBackOutline'),
    BulbOutline: icon('BulbOutline'),
    CalendarOutline: icon('CalendarOutline'),
    ChatbubbleEllipsesOutline: icon('ChatbubbleEllipsesOutline'),
    ChatbubbleOutline: icon('ChatbubbleOutline'),
    CheckmarkCircleOutline: icon('CheckmarkCircleOutline'),
    CloseCircleOutline: icon('CloseCircleOutline'),
    CloseOutline: icon('CloseOutline'),
    CodeSlashOutline: icon('CodeSlashOutline'),
    CodeOutline: icon('CodeOutline'),
    CreateOutline: icon('CreateOutline'),
    CubeOutline: icon('CubeOutline'),
    DocumentTextOutline: icon('DocumentTextOutline'),
    DownloadOutline: icon('DownloadOutline'),
    FolderOpenOutline: icon('FolderOpenOutline'),
    GitBranchOutline: icon('GitBranchOutline'),
    GitCommitOutline: icon('GitCommitOutline'),
    GitMergeOutline: icon('GitMergeOutline'),
    GitPullRequest: icon('GitPullRequest'),
    InformationCircleOutline: icon('InformationCircleOutline'),
    LogoGitlab: icon('LogoGitlab'),
    OpenOutline: icon('OpenOutline'),
    PersonOutline: icon('PersonOutline'),
    PlayOutline: icon('PlayOutline'),
    RefreshOutline: icon('RefreshOutline'),
    SearchOutline: icon('SearchOutline'),
    ShieldCheckmarkOutline: icon('ShieldCheckmarkOutline'),
    TerminalOutline: icon('TerminalOutline'),
    TimeOutline: icon('TimeOutline'),
    WarningOutline: icon('WarningOutline'),
  }
})

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
    { path: '/tasks/:id', name: 'task-view', component: TaskView },
    { path: '/issues/:id', name: 'IssueView', component: { template: '<div>issue</div>' } }
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
    Object.values(mockMessage).forEach(fn => fn.mockReset())
    mockEventSourceInstance.close.mockClear()
    mockEventSourceInstance.onerror = null
    mockEventSourceInstance.addEventListener.mockClear()
    Object.keys(mockEventSourceListeners).forEach(key => delete mockEventSourceListeners[key])
    ;(mockApi.streamTaskLogs as Mock).mockReturnValue(mockEventSourceInstance)
    // Reset auth state to defaults to prevent leaks between tests
    const { authState, isAdmin } = await import('../auth')
    authState.oidcEnabled = false
    authState.user = null
    ;(isAdmin as unknown as { value: boolean }).value = false
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
      status: 'running',
      raw_logs_finalized: false
    })
    ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
    ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: {} })
    ;(mockApi.getIssue as Mock).mockResolvedValue({ tasks: [] })
    ;(mockApi.getTaskArchive as Mock).mockRejectedValue({ response: { status: 404 } })
    ;(mockApi.downloadTaskArchive as Mock).mockResolvedValue(new Blob(['archive']))

    wrapper = mount(TaskView, {
      global: {
        plugins: [router]
      }
    })

    // Wait for onMounted to complete
    await vi.waitFor(() => {
      return (mockApi.getTask as Mock).mock.calls.length > 0
    })

    await flushPromises()
    await nextTick()

    return wrapper
  }

  const showRawLogsTab = async () => {
    const processPanel = wrapper.findComponent({ name: 'TaskProcessPanel' })
    expect(processPanel.exists()).toBe(true)
    ;(processPanel.vm as any).activeTab = 'raw'
    await nextTick()
  }

  it('switches the existing prompt card to the persisted final prompt', async () => {
    await mountComponent({ rendered_prompt: 'Final **rendered** prompt' })
    const card = wrapper.find('[data-testid="task-prompt-card"]')
    const switcher = card.find('[role="tablist"]')
    const userButton = card.find('#task-prompt-user-tab')
    expect(card.text()).toContain('taskView.userPrompt')
    expect(switcher.classes()).toContain('task-prompt-view-switch')
    expect(userButton.attributes('aria-selected')).toBe('true')
    const finalButton = card.findAll('button').find((button) =>
      button.text().includes('taskView.finalRunPrompt')
    )
    await finalButton!.trigger('click')
    expect(wrapper.vm.promptView).toBe('final')
    expect(userButton.attributes('aria-selected')).toBe('false')
    expect(finalButton!.attributes('aria-selected')).toBe('true')
    expect(finalButton!.classes()).toContain('task-prompt-view-switch__button--active')
    expect(card.html()).toContain('Final')
  })

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

    it('should display task summary and header actions', async () => {
      await mountComponent({ task_mode: 'plan' })

      await vi.waitFor(() => {
        return wrapper.find('[data-testid="task-actions"]').exists()
      })

      // Header carries compact actions; the detail card is only rendered when an action needs extra context.
      expect(wrapper.find('.task-metadata-panel').exists()).toBe(true)
      expect(wrapper.find('.task-metadata-panel').text()).toContain('taskView.taskMode')
      expect(wrapper.find('.task-metadata-panel').text()).toContain('taskView.taskModePlan')
      expect(wrapper.find('[data-testid="task-actions"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="task-actions-card"]').exists()).toBe(false)
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

    it('shows an icon on the existing retry task header action', async () => {
      await mountComponent({ status: 'failed' })
      wrapper.vm.activeRetryTask = createMockTask({ id: 2, retry_source_task_id: 1 })
      await nextTick()

      const retryLink = wrapper
        .findAll('.task-actions__linked-task button')
        .find((button) => button.text().includes('Task #2'))

      expect(retryLink).toBeTruthy()
      expect(retryLink!.find('.n-icon').exists()).toBe(true)
      expect(retryLink!.find('.n-icon').attributes('data-icon')).toBe('OpenOutline')
    })

    it('orders retry actions before runtime archive and refresh actions', async () => {
      await mountComponent({ status: 'failed' })
      wrapper.vm.archiveMetadata = {
        archive_name: 'task-1-runtime-archive.tar.gz',
        archive_size_bytes: 1024,
        created_at: '2026-04-01T10:00:00Z',
        file_exists: true,
      }
      await nextTick()

      const actionLabels = wrapper
        .find('.task-actions__toolbar')
        .findAll('button.n-button')
        .map(button => button.text())

      expect(actionLabels).toEqual([
        'common.retry',
        'taskView.retryWithSchedule',
        'taskView.downloadRuntimeArchive',
        'common.refresh',
      ])
    })

    it('should open scheduled retry drawer from the header action', async () => {
      await mountComponent({ status: 'failed' })

      await vi.waitFor(() => {
        return wrapper.vm.task !== null
      })

      const scheduleRetryButton = wrapper
        .findAll('button')
        .find((button) => button.text().includes('taskView.retryWithSchedule'))
      expect(scheduleRetryButton).toBeTruthy()

      await scheduleRetryButton!.trigger('click')
      await flushPromises()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(wrapper.find('[data-testid="task-actions-card"]').exists()).toBe(false)
      expect(wrapper.find('.n-date-picker').exists()).toBe(true)
      expect(wrapper.text()).toContain('taskView.scheduleRetry')
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
    })

    it('should keep scheduled retry drawer open when selecting a heatmap time', async () => {
      await mountComponent({ status: 'failed' })

      const scheduleRetryButton = wrapper
        .findAll('button')
        .find((button) => button.text().includes('taskView.retryWithSchedule'))
      await scheduleRetryButton!.trigger('click')
      await flushPromises()

      const selectedTime = Date.now() + 3600000
      wrapper.vm.handleScheduleHeatmapCellClick(selectedTime)
      await nextTick()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(wrapper.vm.retryScheduleDatetime).toBe(selectedTime)
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

    it('loads runtime archive metadata for terminal tasks', async () => {
      await mountComponent({ status: 'completed' })
      ;(mockApi.getTaskArchive as Mock).mockResolvedValue({
        archive_name: 'task-1-runtime-archive.tar.gz',
        archive_size_bytes: 42,
        created_at: '2026-05-01T10:00:00Z',
        file_exists: true,
      })

      await wrapper.vm.fetchArchiveMetadata()
      await nextTick()

      expect(mockApi.getTaskArchive).toHaveBeenCalledWith(1)
      expect(wrapper.text()).toContain('taskView.downloadRuntimeArchive')
    })

    it('shows expired badge and disables download when archive file was cleaned up', async () => {
      await mountComponent({ status: 'completed' })
      ;(mockApi.getTaskArchive as Mock).mockResolvedValue({
        archive_name: 'task-1-runtime-archive.tar.gz',
        archive_size_bytes: 42,
        created_at: '2026-05-01T10:00:00Z',
        file_exists: false,
      })

      await wrapper.vm.fetchArchiveMetadata()
      await nextTick()

      expect(wrapper.text()).toContain('taskView.downloadRuntimeArchive')
      expect(wrapper.text()).toContain('taskView.archiveFileExpired')
      const buttons = wrapper.findAllComponents({ name: 'NButton' })
      const downloadButton = buttons.find(
        (b) => b.text() === 'taskView.downloadRuntimeArchive',
      )
      expect(downloadButton).toBeTruthy()
      expect(downloadButton!.props('disabled')).toBe(true)
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

    it('downloads the runtime archive when requested', async () => {
      Object.defineProperty(URL, 'createObjectURL', { value: vi.fn(), configurable: true })
      Object.defineProperty(URL, 'revokeObjectURL', { value: vi.fn(), configurable: true })
      const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:archive')
      const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
      const archiveBlob = new Blob(['archive'])
      ;(mockApi.downloadTaskArchive as Mock).mockResolvedValue(archiveBlob)
      await mountComponent({ status: 'completed' })
      wrapper.vm.archiveMetadata = {
        archive_name: 'task-1-runtime-archive.tar.gz',
        archive_size_bytes: 42,
        created_at: '2026-05-01T10:00:00Z',
        file_exists: true,
      }
      await wrapper.vm.handleDownloadArchive()

      expect(mockApi.downloadTaskArchive).toHaveBeenCalledWith(1)
      expect(createObjectURL).toHaveBeenCalledWith(archiveBlob)
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:archive')

      createObjectURL.mockRestore()
      revokeObjectURL.mockRestore()
    })

    it('does not attempt download when archive file is expired', async () => {
      await mountComponent({ status: 'completed' })
      ;(mockApi.downloadTaskArchive as Mock).mockResolvedValue(new Blob(['archive']))
      wrapper.vm.archiveMetadata = {
        archive_name: 'task-1-runtime-archive.tar.gz',
        archive_size_bytes: 42,
        created_at: '2026-05-01T10:00:00Z',
        file_exists: false,
      }
      await wrapper.vm.handleDownloadArchive()

      expect(mockApi.downloadTaskArchive).not.toHaveBeenCalled()
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

    it('should open reschedule drawer with the current task', async () => {
      await mountComponent({
        status: 'pending',
        scheduled_at: new Date(Date.now() + 60 * 60 * 1000).toISOString()
      })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })

      const rescheduleButton = wrapper
        .findAll('button')
        .find((button) => button.text().includes('taskView.rescheduleTask'))
      expect(rescheduleButton).toBeTruthy()

      await rescheduleButton!.trigger('click')
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'RescheduleDrawer' })
      expect(wrapper.vm.showRescheduleDrawer).toBe(true)
      expect(drawer.props('show')).toBe(true)
      expect(drawer.props('task').id).toBe(1)
    })

    it('should update task when reschedule drawer emits rescheduled', async () => {
      const scheduledAt = new Date(Date.now() + 60 * 60 * 1000).toISOString()
      await mountComponent({ status: 'pending', scheduled_at: scheduledAt })
      const updatedTask = createMockTaskWithStatus('pending', {
        scheduled_at: new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString()
      })

      const drawer = wrapper.findComponent({ name: 'RescheduleDrawer' })
      drawer.vm.$emit('rescheduled', updatedTask)
      await nextTick()

      expect(wrapper.vm.task).toEqual(updatedTask)
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

      await flushPromises()
      await showRawLogsTab()
      await nextTick()

      expect(wrapper.find('.log-content').exists()).toBe(true)
    })

    it('should display task logs for completed tasks', async () => {
      await mountComponent({ status: 'completed' })

      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })

      await flushPromises()
      await showRawLogsTab()
      await nextTick()

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

      // Restore visibilityState to avoid leaking into subsequent tests
      Object.defineProperty(document, 'visibilityState', {
        value: 'visible',
        configurable: true
      })
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

    it('contextCompactCount returns 0 when there are no context_compact logs', async () => {
      ;(mockApi.getTaskLogs as Mock).mockResolvedValue([
        createMockTaskLog({ log_type: 'assistant_text', message: 'summary' })
      ])
      await mountComponent({ status: 'completed' })
      await vi.waitFor(() => mockApi.getTaskLogs.mock.calls.length > 0)
      await nextTick()

      expect(wrapper.vm.contextCompactCount).toBe(0)
    })

    it('contextCompactCount returns correct count and lastAssistantLog is the last assistant_text log', async () => {
      await mountComponent({ status: 'completed' })

      // Override logs after mounting so mountComponent's default setup doesn't win
      ;(mockApi.getTaskLogs as Mock).mockResolvedValue([
        createMockTaskLog({ log_type: 'assistant_text', message: 'First summary' }),
        createMockTaskLog({ log_type: 'context_compact' }),
        createMockTaskLog({ log_type: 'context_compact' }),
        createMockTaskLog({ log_type: 'assistant_text', message: 'Last summary' })
      ])

      await wrapper.vm.refreshTask()
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.contextCompactCount).toBe(2)
      expect(wrapper.vm.lastAssistantLog).not.toBeNull()
      expect(wrapper.vm.lastAssistantLog.message).toBe('Last summary')
    })

    it('deliverySummaryLog returns the latest delivery_summary log', async () => {
      await mountComponent({ status: 'completed' })

      ;(mockApi.getTaskLogs as Mock).mockResolvedValue([
        createMockTaskLog({ log_type: 'delivery_summary', message: 'Old delivery summary' }),
        createMockTaskLog({ log_type: 'assistant_text', message: 'Raw assistant summary' }),
        createMockTaskLog({ log_type: 'delivery_summary', message: 'Final delivery summary' })
      ])

      await wrapper.vm.refreshTask()
      await flushPromises()
      await nextTick()

      expect(wrapper.vm.deliverySummaryLog).not.toBeNull()
      expect(wrapper.vm.deliverySummaryLog.message).toBe('Final delivery summary')
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

  describe('action error handling', () => {
    it('should handle cancelTask error gracefully', async () => {
      await mountComponent({ status: 'running' })
      ;(mockApi.cancelTask as Mock).mockRejectedValue(new Error('Cancel failed'))

      await wrapper.vm.handleCancel()

      expect(wrapper.vm.actionLoading).toBe(false)
    })

    it('should handle retryTask error gracefully', async () => {
      await mountComponent({ status: 'failed' })
      ;(mockApi.retryTask as Mock).mockRejectedValue(new Error('Retry failed'))

      await wrapper.vm.handleRetry()

      expect(wrapper.vm.actionLoading).toBe(false)
    })

    it('should handle executeTask error gracefully', async () => {
      await mountComponent({ status: 'pending' })
      ;(mockApi.executeTask as Mock).mockRejectedValue(new Error('Execute failed'))

      await wrapper.vm.handleExecute()

      expect(wrapper.vm.actionLoading).toBe(false)
    })
  })

  describe('handleRetryWithSchedule validation', () => {
    it('should not call API when no datetime is selected', async () => {
      await mountComponent({ status: 'failed' })

      wrapper.vm.retryScheduleDatetime = null

      await wrapper.vm.handleRetryWithSchedule()

      expect(mockApi.retryTask).not.toHaveBeenCalled()
    })

    it('should not call API when datetime is in the past', async () => {
      await mountComponent({ status: 'failed' })

      wrapper.vm.retryScheduleDatetime = Date.now() - 1000

      await wrapper.vm.handleRetryWithSchedule()

      expect(mockApi.retryTask).not.toHaveBeenCalled()
    })

    it('should handle retryTask with schedule API error', async () => {
      await mountComponent({ status: 'failed' })
      ;(mockApi.retryTask as Mock).mockRejectedValue(new Error('Retry failed'))

      wrapper.vm.retryScheduleDatetime = Date.now() + 86400000

      await wrapper.vm.handleRetryWithSchedule()

      expect(wrapper.vm.actionLoading).toBe(false)
    })

    it('should clear retryScheduleDatetime on success', async () => {
      await mountComponent({ status: 'failed' })
      ;(mockApi.retryTask as Mock).mockResolvedValue(undefined)
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('pending'))

      wrapper.vm.retryScheduleDatetime = Date.now() + 86400000

      await wrapper.vm.handleRetryWithSchedule()

      expect(wrapper.vm.retryScheduleDatetime).toBeNull()
    })
  })

  describe('onRawTabOpen and onRawTabClose', () => {
    it('should stream running-task raw logs from the first persisted chunk', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({
        container_id: 'container-123',
        logs: 'first line\n',
        status: 'running',
        source: 'db',
        last_sequence_no: 1,
        raw_logs_finalized: false
      })

      await wrapper.vm.onRawTabOpen()

      expect(mockApi.getTaskContainerLogs).toHaveBeenCalledWith(1, 'db')
      expect(EventSource).toHaveBeenCalledWith(
        '/api/tasks/1/raw-log-stream?since_sequence_no=1'
      )

      mockEventSourceListeners.batch?.({
        data: JSON.stringify([
          { sequence_no: 2, content: 'latest line\n' }
        ])
      })
      await nextTick()

      expect(wrapper.vm.containerLogs).toBe('first line\nlatest line\n')
    })

    it('should ignore replayed raw-log chunks and reconnect from the latest sequence', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValueOnce({
        container_id: 'container-123',
        logs: 'one\ntwo\n',
        status: 'running',
        source: 'db',
        last_sequence_no: 2,
        raw_logs_finalized: false
      })
      await wrapper.vm.onRawTabOpen()

      mockEventSourceListeners.batch?.({
        data: JSON.stringify([
          { sequence_no: 2, content: 'two\n' },
          { sequence_no: 3, content: 'three\n' }
        ])
      })

      expect(wrapper.vm.containerLogs).toBe('one\ntwo\nthree\n')

      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValueOnce({
        container_id: 'container-123',
        logs: 'one\ntwo\nthree\n',
        status: 'running',
        source: 'db',
        last_sequence_no: 3,
        raw_logs_finalized: false
      })
      mockEventSourceInstance.onerror?.()
      await wrapper.vm.reconnectLogStream()

      expect(mockApi.getTaskContainerLogs).toHaveBeenCalledTimes(2)
      expect(wrapper.vm.containerLogs).toBe('one\ntwo\nthree\n')
      expect(EventSource).toHaveBeenLastCalledWith(
        '/api/tasks/1/raw-log-stream?since_sequence_no=3'
      )
    })

    it('should keep raw logs larger than the former 200 KB limit', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })
      const fullLog = 'x'.repeat(300_000)
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({
        container_id: 'container-123',
        logs: fullLog,
        status: 'running',
        source: 'db',
        last_sequence_no: 1,
        raw_logs_finalized: false
      })
      await wrapper.vm.onRawTabOpen()

      expect(wrapper.vm.containerLogs).toHaveLength(300_000)
    })

    it('should replace streamed content with the final DB snapshot without duplication', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })
      ;(mockApi.getTaskContainerLogs as Mock)
        .mockResolvedValueOnce({
          container_id: 'container-123',
          logs: '',
          status: 'running',
          source: 'db',
          last_sequence_no: 0,
          raw_logs_finalized: false
        })
        .mockResolvedValueOnce({
          container_id: 'container-123',
          logs: 'one\ntwo\n',
          status: 'completed',
          source: 'db',
          last_sequence_no: 2,
          raw_logs_finalized: true
        })
      await wrapper.vm.onRawTabOpen()

      mockEventSourceListeners.batch?.({
        data: JSON.stringify([
          { sequence_no: 1, content: 'one\n' },
          { sequence_no: 2, content: 'two\n' }
        ])
      })
      mockEventSourceListeners.done?.({ data: '{}' })
      await flushPromises()

      expect(wrapper.vm.containerLogs).toBe('one\ntwo\n')
    })

    it('should keep streaming a cancelled task until raw logs are finalized', async () => {
      await mountComponent({ status: 'cancelled', container_id: 'container-123' })
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({
        container_id: 'container-123',
        logs: 'before cancel\n',
        status: 'cancelled',
        source: 'db',
        last_sequence_no: 1,
        raw_logs_finalized: false
      })

      await wrapper.vm.onRawTabOpen()

      expect(EventSource).toHaveBeenCalledWith(
        '/api/tasks/1/raw-log-stream?since_sequence_no=1'
      )
      mockEventSourceListeners.batch?.({
        data: JSON.stringify([{ sequence_no: 2, content: 'final line\n' }])
      })

      expect(wrapper.vm.containerLogs).toBe('before cancel\nfinal line\n')
    })

    it('should not open a stream for a cancelled task whose raw logs are finalized', async () => {
      await mountComponent({ status: 'cancelled', container_id: 'container-123' })
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({
        container_id: 'container-123',
        logs: 'complete log\n',
        status: 'cancelled',
        source: 'db',
        last_sequence_no: 2,
        raw_logs_finalized: true
      })

      await wrapper.vm.onRawTabOpen()

      expect(wrapper.vm.containerLogs).toBe('complete log\n')
      expect(EventSource).not.toHaveBeenCalled()
    })

    it('should fetch container logs for completed tasks via onRawTabOpen using source=db', async () => {
      await mountComponent({ status: 'completed', container_id: 'container-123' })

      await wrapper.vm.onRawTabOpen()

      expect(mockApi.getTaskContainerLogs).toHaveBeenCalledWith(1, 'db')
      expect(wrapper.vm.containerLogs).toBe('Container log content')
    })

    it('should pass source=db when fetching logs for completed tasks', async () => {
      await mountComponent({ status: 'completed', container_id: 'container-123' })

      await wrapper.vm.onRawTabOpen()

      // Verify it always uses 'db' source for completed tasks
      expect(mockApi.getTaskContainerLogs).toHaveBeenCalledWith(1, 'db')
    })

    it('should close log stream on onRawTabClose', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })

      // Open raw tab to establish SSE connection
      await wrapper.vm.onRawTabOpen()

      // Clear the close mock after open
      mockEventSourceInstance.close.mockClear()

      // Close the tab
      wrapper.vm.onRawTabClose()

      // Verify EventSource was closed
      expect(mockEventSourceInstance.close).toHaveBeenCalled()
    })
  })

  describe('openScheduleDrawer', () => {
    it('should open drawer and fetch scheduled tasks', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
      expect(mockApi.getConfig).toHaveBeenCalled()
    })

    it('should handle getScheduledTasks error gracefully', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })
      ;(mockApi.getScheduledTasks as Mock).mockRejectedValue(new Error('API Error'))

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      expect(wrapper.vm.showScheduleDrawer).toBe(true)
      expect(wrapper.vm.scheduledTasksForPreview).toEqual([])
    })

    it('should handle getConfig error gracefully', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })
      ;(mockApi.getConfig as Mock).mockRejectedValue(new Error('Config Error'))

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      // Should not crash
      expect(wrapper.vm.showScheduleDrawer).toBe(true)
    })

    it('should set slot config from API response', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })
      ;(mockApi.getConfig as Mock).mockResolvedValue({
        runtime: { slot_max_tasks: 5, slot_max_tasks_enforce: true }
      })

      await wrapper.vm.openScheduleDrawer()
      await flushPromises()

      expect(wrapper.vm.slotMaxTasks).toBe(5)
      expect(wrapper.vm.slotEnforce).toBe(true)
    })
  })

  describe('handleScheduleHeatmapCellClick', () => {
    it('should set retryScheduleDatetime and keep retry drawer open', async () => {
      await mountComponent({ status: 'failed' })

      wrapper.vm.showScheduleDrawer = true
      const clickTime = Date.now() + 3600000

      wrapper.vm.handleScheduleHeatmapCellClick(clickTime)

      expect(wrapper.vm.retryScheduleDatetime).toBe(clickTime)
      expect(wrapper.vm.showScheduleDrawer).toBe(true)
    })
  })

  describe('no actions display', () => {
    it('should show empty state for completed tasks', async () => {
      await mountComponent({ status: 'completed' })

      expect(wrapper.vm.hasActions).toBe(false)
      expect(wrapper.find('.task-actions__empty').exists()).toBe(true)
    })

    it('should not show cancel button for completed tasks', async () => {
      await mountComponent({ status: 'completed' })

      const cancelCommands = wrapper
        .findAll('.task-actions__command')
        .filter((command) => command.text().includes('common.cancel'))
      expect(cancelCommands.length).toBe(0)
    })
  })

  describe('canReschedule computed', () => {
    it('should return false for running tasks', async () => {
      await mountComponent({ status: 'running' })

      expect(wrapper.vm.canReschedule).toBe(false)
    })

    it('should return false for pending tasks without scheduled_at', async () => {
      await mountComponent({ status: 'pending', scheduled_at: null })

      expect(wrapper.vm.canReschedule).toBe(false)
    })

    it('should return true for pending tasks with scheduled_at', async () => {
      await mountComponent({ status: 'pending', scheduled_at: '2026-04-01T10:00:00Z' })

      expect(wrapper.vm.canReschedule).toBe(true)
    })
  })

  describe('initialLoading computed', () => {
    it('should be true when loading and not yet loaded', async () => {
      ;(mockApi.getTask as Mock).mockImplementation(() => new Promise(() => {})) // Never resolves
      ;(mockApi.getTaskLogs as Mock).mockResolvedValue([])
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({ logs: '' })

      wrapper = mount(TaskView, {
        global: {
          plugins: [router]
        }
      })

      // Component is loading
      await nextTick()
      expect(wrapper.vm.initialLoading).toBe(true)
    })
  })

  describe('statusColors', () => {
    it('should map all task statuses to correct color types', async () => {
      await mountComponent()

      expect(wrapper.vm.statusColors['pending']).toBe('default')
      expect(wrapper.vm.statusColors['queued']).toBe('info')
      expect(wrapper.vm.statusColors['running']).toBe('warning')
      expect(wrapper.vm.statusColors['completed']).toBe('success')
      expect(wrapper.vm.statusColors['failed']).toBe('error')
      expect(wrapper.vm.statusColors['cancelled']).toBe('default')
    })
  })

  describe('resetLogsState', () => {
    it('should clear all log state and close streams', async () => {
      await mountComponent({ status: 'running', container_id: 'container-123' })

      // Open raw tab to create an SSE connection
      await wrapper.vm.onRawTabOpen()

      // Populate some log state
      wrapper.vm.taskLogs = [createMockTaskLog()]
      wrapper.vm.logs = 'some logs'
      wrapper.vm.containerLogs = 'container logs'

      mockEventSourceInstance.close.mockClear()

      wrapper.vm.resetLogsState()

      expect(wrapper.vm.taskLogs).toEqual([])
      expect(wrapper.vm.logs).toBe('')
      expect(wrapper.vm.containerLogs).toBe('')
      expect(mockEventSourceInstance.close).toHaveBeenCalled()
    })
  })

  describe('append follow-up shortcut', () => {
    it('opens the create task drawer from the result panel for the latest issue task', async () => {
      await mountComponent({
        id: 1,
        issue_id: 10,
        status: 'completed',
        created_at: '2026-04-01T10:00:00Z',
        completed_at: '2026-04-01T10:05:00Z'
      })

      wrapper.vm.issueTasks = [
        createMockTask({ id: 1, issue_id: 10, created_at: '2026-04-01T10:00:00Z' }),
        createMockTask({ id: 2, issue_id: 10, created_at: '2026-04-01T09:00:00Z' })
      ]
      wrapper.vm.issueDescription = 'Issue context for follow-up'
      wrapper.vm.issueStatus = 'open'
      await nextTick()

      const resultPanel = wrapper.findComponent({ name: 'TaskResultPanel' })
      expect(resultPanel.exists()).toBe(true)
      expect(resultPanel.props('canAppendFollowupTask')).toBe(true)

      resultPanel.vm.$emit('append-followup-task')
      await nextTick()

      expect(wrapper.vm.showCreateDrawer).toBe(true)
      const createDrawer = wrapper
        .findAllComponents({ name: 'TaskFormDrawer' })
        .find((drawer) => drawer.props('mode') === 'create')
      expect(createDrawer).toBeTruthy()
      expect(createDrawer!.props('show')).toBe(true)
      expect(createDrawer!.props('issueId')).toBe(10)
      expect(createDrawer!.props('issueDescription')).toBe('Issue context for follow-up')

      createDrawer!.vm.$emit('created', createMockTask({ id: 99, issue_id: 10 }))
      await flushPromises()
      expect(router.currentRoute.value.path).toBe('/tasks/99')
    })

    it('does not enable the append shortcut when a newer issue task exists', async () => {
      await mountComponent({
        id: 1,
        issue_id: 10,
        status: 'completed',
        created_at: '2026-04-01T10:00:00Z',
        completed_at: '2026-04-01T10:05:00Z'
      })

      wrapper.vm.issueTasks = [
        createMockTask({ id: 1, issue_id: 10, created_at: '2026-04-01T10:00:00Z' }),
        createMockTask({ id: 2, issue_id: 10, created_at: '2026-04-01T11:00:00Z' })
      ]
      wrapper.vm.issueStatus = 'open'
      await nextTick()

      const resultPanel = wrapper.findComponent({ name: 'TaskResultPanel' })
      expect(resultPanel.exists()).toBe(true)
      expect(resultPanel.props('canAppendFollowupTask')).toBe(false)
    })
  })

  describe('isActiveTaskStatus', () => {
    it('should return false for null and undefined', async () => {
      await mountComponent()

      expect(wrapper.vm.isActiveTaskStatus(null)).toBe(false)
      expect(wrapper.vm.isActiveTaskStatus(undefined)).toBe(false)
    })
  })

  describe('terminalLogHtml', () => {
    it('should return empty string when no logs', async () => {
      ;(mockApi.getTask as Mock).mockResolvedValue(createMockTaskWithStatus('pending'))
      ;(mockApi.getTaskLogs as Mock).mockResolvedValue([])
      ;(mockApi.getTaskContainerLogs as Mock).mockResolvedValue({ logs: '' })
      ;(mockApi.getScheduledTasks as Mock).mockResolvedValue([])
      ;(mockApi.getConfig as Mock).mockResolvedValue({ runtime: {} })

      wrapper = mount(TaskView, {
        global: { plugins: [router] }
      })

      await vi.waitFor(() => {
        return (mockApi.getTask as Mock).mock.calls.length > 0
      })
      // Wait for fetchLogs to complete
      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })
      await nextTick()

      expect(wrapper.vm.terminalLogHtml).toBe('')
    })

    it('should prefer containerLogs over logs', async () => {
      await mountComponent({ status: 'running' })

      // Wait for all mount async operations
      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })
      await nextTick()

      wrapper.vm.containerLogs = 'container output'
      await nextTick()

      expect(wrapper.vm.terminalLogHtml).toContain('container output')
    })

    it('should fall back to logs when containerLogs is empty', async () => {
      await mountComponent({ status: 'completed' })

      // Wait for fetchLogs to complete
      await vi.waitFor(() => {
        return (mockApi.getTaskLogs as Mock).mock.calls.length > 0
      })
      await nextTick()

      // containerLogs is empty for completed tasks, logs is populated from fetchLogs
      expect(wrapper.vm.containerLogs).toBe('')
      expect(wrapper.vm.terminalLogHtml).toContain('Log entry 1')
    })
  })
})
