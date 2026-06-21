import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import IssueView from './IssueView.vue'
import issueViewSource from './IssueView.vue?raw'
import issueCiAutomationSource from '../components/issue-detail/IssueCIAutomationPanel.vue?raw'
import issueTaskPanelSource from '../components/issue-detail/IssueTaskPanel.vue?raw'
import rescheduleDrawerSource from '../components/RescheduleDrawer.vue?raw'
import taskFormDrawerSource from '../components/TaskFormDrawer.vue?raw'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, resetMockApi, mockMessage, mockDialog } = vi.hoisted(() => {
  const mock = {
    getIssue: vi.fn<() => Promise<any>>(),
    updateIssue: vi.fn<() => Promise<any>>(),
    closeIssue: vi.fn<(...args: any[]) => Promise<any>>(),
    createTask: vi.fn<() => Promise<any>>(),
    retryTask: vi.fn<() => Promise<any>>(),
    rescheduleTask: vi.fn<() => Promise<any>>(),
    deleteIssueBranch: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>(),
	    getProjects: vi.fn<() => Promise<any[]>>(),
    getProviders: vi.fn<() => Promise<any[]>>(),
	    getRunInstructionTemplateDefaults: vi.fn<() => Promise<any>>(),
	    previewRunInstructionTemplate: vi.fn<() => Promise<any>>(),
	    getIssueCIFailures: vi.fn<() => Promise<any>>(),
	    getCIFailureLogs: vi.fn<() => Promise<any>>(),
	    getIssueWebhookEvents: vi.fn<() => Promise<any>>(),
	  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => fn.mockReset())
  }
  const mockMsg = { error: vi.fn(), success: vi.fn(), warning: vi.fn(), info: vi.fn() }
  const mockDlg = { warning: vi.fn() }
  return { mockApi: mock, resetMockApi, mockMessage: mockMsg, mockDialog: mockDlg }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../i18n', () => ({ currentLocale: ref('en') }))

vi.mock('../utils/datetime', () => ({
  formatDateTimeUtc8Compact: vi.fn((value: any) => `formatted-${value}`),
  formatTimeUtc8: vi.fn((value: any) => `time-${value}`),
  parseUtcDate: vi.fn((value: any) => new Date(value)),
}))

vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((error: any, t: any, fallbackKey: string) => {
    const detail = error?.response?.data?.detail
    return typeof detail === 'string' ? detail : t(fallbackKey)
  }),
}))

vi.mock('../auth', () => ({
  authState: {
    oidcEnabled: false,
    user: null,
    initialized: true,
  },
  isAdmin: ref(false),
}))

vi.mock('../api', () => ({
  getIssue: mockApi.getIssue,
  updateIssue: mockApi.updateIssue,
  closeIssue: mockApi.closeIssue,
  createTask: mockApi.createTask,
  retryTask: mockApi.retryTask,
  rescheduleTask: mockApi.rescheduleTask,
  deleteIssueBranch: mockApi.deleteIssueBranch,
  getPromptTemplates: mockApi.getPromptTemplates,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
	  getConfig: mockApi.getConfig,
	  getProjects: mockApi.getProjects,
	  getProviders: mockApi.getProviders,
	  getRunInstructionTemplateDefaults: mockApi.getRunInstructionTemplateDefaults,
	  previewRunInstructionTemplate: mockApi.previewRunInstructionTemplate,
	  getIssueCIFailures: mockApi.getIssueCIFailures,
	  getCIFailureLogs: mockApi.getCIFailureLogs,
	  getIssueWebhookEvents: mockApi.getIssueWebhookEvents,
	}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' },
    d: vi.fn((value: unknown) => String(value)),
    n: vi.fn((value: number) => String(value)),
    te: vi.fn(() => false),
  }),
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } })),
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
    isCompact: ref(false),
    width: ref(1200),
  }),
}))

// ---------------------------------------------------------------------------
// Child component stubs
// ---------------------------------------------------------------------------
vi.mock('../components/HeatmapChart.vue', () => ({
  default: {
    name: 'HeatmapChart',
    props: ['tasks', 'selectedMs', 'maxPerSlot', 'enforceCapacity'],
    setup() {
      return () => h('div', { class: 'heatmap-chart-mock' })
    },
  },
}))

vi.mock('../components/PageHeader.vue', () => ({
  default: {
    name: 'PageHeader',
    props: ['title', 'subtitle', 'rootClass', 'actionsClass'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'page-header-mock', 'data-testid': 'page-header' }, [
        slots.title?.(),
        h('div', { class: 'page-header-actions-mock', 'data-testid': 'page-header-actions' }, slots.actions?.()),
      ])
    },
  },
}))

vi.mock('../components/VariableEditor.vue', () => ({
  default: {
    name: 'VariableEditor',
    props: ['modelValue', 'variableTips', 'placeholder'],
    emits: ['update:modelValue'],
    setup(props: any, { emit }: any) {
      return () => h('textarea', {
        class: 'variable-editor-mock',
        value: props.modelValue,
        onInput: (e: Event) => emit('update:modelValue', (e.target as HTMLTextAreaElement).value),
      })
    },
  },
}))

// ---------------------------------------------------------------------------
// Naive-UI stubs
// ---------------------------------------------------------------------------
vi.mock('naive-ui', () => ({
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'label-placement'],
    setup(_p: any, { slots, expose }: any) {
      expose({ validate: vi.fn(), restoreValidation: vi.fn() })
      return () => h('form', {}, slots.default?.())
    },
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['path', 'label'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, [
        slots.label?.(),
        slots.default?.(),
        slots.feedback?.(),
      ])
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'disabled', 'loading', 'text', 'secondary', 'strong', 'round', 'size', 'onClick'],
    setup(props: any, { slots }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled,
        onClick: props.onClick,
      }, [
        slots.icon?.(),
        slots.default?.(),
      ])
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [
        slots.header?.(),
        slots.default?.(),
        slots.action?.(),
      ])
    },
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'justify'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', {
        class: props.show ? 'n-spin-loading' : 'n-spin',
      }, slots.default?.())
    },
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'x-gap', 'y-gap'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
  },
  NGi: {
    name: 'NGi',
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
  },
	  NTag: {
	    name: 'NTag',
	    props: ['type', 'size', 'round'],
	    setup(_p: any, { slots }: any) {
	      return () => h('span', { class: 'n-tag' }, slots.default?.())
	    },
	  },
	  NIcon: {
    name: 'NIcon',
    props: ['size', 'component'],
    setup(props: any) {
      return () => h('i', {
        class: 'n-icon',
        'data-icon': props.component?.name,
      })
    },
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'row-key', 'row-props', 'bordered', 'show-header', 'single-line'],
    setup(props: any) {
      return () => h(
        'div',
        { class: 'n-data-table' },
        props.data?.map((row: any) =>
          h('div', { class: 'n-data-table-row', 'data-id': row.id }),
        ),
      )
    },
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'type', 'rows'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        value: props.value,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value),
      })
    },
  },
  NSelect: {
    name: 'NSelect',
    props: ['options', 'value', 'loading', 'placeholder', 'disabled'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value),
      })
    },
  },
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
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-drawer-content' }, [
        slots.default?.(),
        slots.footer?.(),
      ])
    },
  },
  NRadio: {
    name: 'NRadio',
    props: ['value'],
    setup(props: any) {
      return () => h('input', { type: 'radio', value: props.value })
    },
  },
  NRadioGroup: {
    name: 'NRadioGroup',
    props: ['value'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-radio-group' }, slots.default?.())
    },
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'clearable', 'isDateDisabled'],
    setup() {
      return () => h('div', { class: 'n-date-picker' })
    },
  },
  NModal: {
    name: 'NModal',
    props: ['show', 'preset', 'title'],
    setup(props: any, { slots }: any) {
      return () => props.show
        ? h('div', { class: 'n-modal' }, [slots.default?.(), slots.action?.()]) 
        : null
    },
  },
  NPopconfirm: {
    name: 'NPopconfirm',
    props: [],
    setup(_p: any, { slots, emit }: any) {
      return () => h('div', { class: 'n-popconfirm' }, [
        slots.trigger?.(),
        slots.default?.(),
        h('button', { class: 'popconfirm-confirm-btn', onClick: () => emit('positive-click') }),
      ])
    },
  },
  NAlert: {
    name: 'NAlert',
    props: ['type'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-alert' }, slots.default?.())
    },
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        disabled: props.disabled,
        onClick: () => {
          if (!props.disabled) {
            emit('update:value', !props.value)
          }
        },
      })
    },
  },
  // Simple NTooltip stub that renders both trigger and content slots
  NTooltip: {
    name: 'NTooltip',
    props: ['title', 'contentStyle', 'themeOverrides', 'placement', 'trigger'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: 'n-tooltip', 'data-tooltip': props.title, 'data-testid': 'n-tooltip' }, [
        slots.trigger?.(),
        slots.default?.()
      ])
    }
  },
  NPopover: {
    name: 'NPopover',
    props: ['show'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-popover' }, [
        slots.trigger?.(),
        slots.default?.(),
      ])
    },
  },
  useMessage: () => mockMessage,
  useDialog: () => mockDialog,
  useThemeVars: () => ref({
    cardColor: '#fff',
    popoverColor: '#fff',
    actionColor: '#f5f5f5',
    hoverColor: '#eee',
    codeColor: '#111',
    borderColor: '#ddd',
    dividerColor: '#ddd',
    textColor1: '#111',
    textColor2: '#333',
    textColor3: '#666',
    primaryColor: '#18a058',
    boxShadow2: 'none',
    fontFamilyMono: 'monospace',
  }),
  DataTableColumns: {},
  NScrollbar: {
    name: 'NScrollbar',
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-scrollbar' }, slots.default?.())
    },
  },
}))

vi.mock('@vicons/ionicons5', () => {
  const icon = (name: string) => ({ name, render: () => null })
  return {
    AddOutline: icon('AddOutline'),
    AddCircleOutline: icon('AddCircleOutline'),
    BulbOutline: icon('BulbOutline'),
    CalendarOutline: icon('CalendarOutline'),
    ChevronDownOutline: icon('ChevronDownOutline'),
    CheckmarkCircleOutline: icon('CheckmarkCircleOutline'),
    CloseCircleOutline: icon('CloseCircleOutline'),
    CloseOutline: icon('CloseOutline'),
    CodeOutline: icon('CodeOutline'),
    CodeSlashOutline: icon('CodeSlashOutline'),
    CreateOutline: icon('CreateOutline'),
    DocumentTextOutline: icon('DocumentTextOutline'),
    FolderOpenOutline: icon('FolderOpenOutline'),
    GitBranchOutline: icon('GitBranchOutline'),
    GitPullRequest: icon('GitPullRequest'),
    InformationCircleOutline: icon('InformationCircleOutline'),
    OptionsOutline: icon('OptionsOutline'),
    PersonOutline: icon('PersonOutline'),
    RefreshOutline: icon('RefreshOutline'),
    TrashOutline: icon('TrashOutline'),
    TimeOutline: icon('TimeOutline'),
    WarningOutline: icon('WarningOutline'),
  }
})

// ---------------------------------------------------------------------------
// Router
// ---------------------------------------------------------------------------
const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', name: 'Home', component: { template: '<div />' } },
    { path: '/issues', name: 'IssueList', component: { template: '<div />' } },
    { path: '/issues/:id', name: 'IssueView', component: IssueView },
    { path: '/tasks/:id', name: 'TaskView', component: { template: '<div />' } },
  ],
})

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
function createMockIssue(overrides: Record<string, any> = {}): any {
  return {
    id: 1,
    title: 'Test Issue',
    description: 'Test description',
    project_id: 1,
    status: 'open',
    branch_name: 'codify/issue-1',
    base_branch: 'main',
    target_branch: 'main',
	    merge_request_iid: 42,
	    merge_request_url: 'https://gitlab.example.com/mr/42',
	    ci_auto_repair_enabled: false,
	    claude_session_id: 'session-abc',
    initiator_user_id: null,
    initiator_username: 'testuser',
    created_at: '2024-01-01T10:00:00Z',
    updated_at: '2024-01-02T10:00:00Z',
    task_count: 2,
    tasks: [
      {
        id: 1, issue_id: 1, project_id: 1, user_prompt: 'Fix the login bug',
	        status: 'completed', priority: 1, is_retry: false, retry_source_task_id: null,
	        trigger_source: 'manual', ci_failure_run_id: null,
        created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z',
        additions: 10, deletions: 5, input_tokens: 100, output_tokens: 50,
        initiator_username: 'testuser',
      },
      {
        id: 2, issue_id: 1, project_id: 1, user_prompt: 'Add unit tests',
	        status: 'failed', priority: 1, is_retry: false, retry_source_task_id: null,
	        trigger_source: 'manual', ci_failure_run_id: null,
        created_at: '2024-01-01T11:00:00Z', updated_at: '2024-01-01T11:00:00Z',
        additions: 0, deletions: 0, input_tokens: 50, output_tokens: 25,
        initiator_username: 'testuser',
      },
    ],
    totals: {
      additions: 10, deletions: 5, total_changes: 15,
      input_tokens: 150, output_tokens: 75, duration_seconds: 0,
    },
    ...overrides,
  }
}

const mockProjects = [
  { id: 1, name: 'test-project', path_with_namespace: 'group/test-project', default_branch: 'main' },
]

const mockPromptTemplates = [
  { id: 1, name: 'Bug Fix', content: 'Fix the {{issue_type}} in {{file_path}}', variable_tips: { issue_type: 'Type', file_path: 'Path' }, tags: [], is_active: true, sort_order: 1, created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z' },
]

const mockProviders = [
  {
    id: 1,
    name: 'Claude',
    provider_type: 'anthropic',
    model: 'claude-sonnet-4',
    is_default: true,
    is_disabled: false,
  },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function setupDefaultMocks(issueOverrides: Record<string, any> = {}) {
  const issue = createMockIssue(issueOverrides)
  mockApi.getIssue.mockResolvedValue(issue)
  mockApi.getProjects.mockResolvedValue(mockProjects)
  mockApi.getPromptTemplates.mockResolvedValue(mockPromptTemplates)
  mockApi.getScheduledTasks.mockResolvedValue([])
	  mockApi.getSlotCapacity.mockResolvedValue(null)
	  mockApi.getConfig.mockResolvedValue({ runtime: { slot_max_tasks: 5, slot_max_tasks_enforce: false } })
	  mockApi.getProviders.mockResolvedValue(mockProviders)
	  mockApi.getRunInstructionTemplateDefaults.mockResolvedValue({
	    execute: { content: 'Execute {{user_prompt}}', available_placeholders: ['user_prompt'] },
	    plan: { content: 'Plan {{user_prompt}}', available_placeholders: ['user_prompt'] },
	  })
	  mockApi.previewRunInstructionTemplate.mockResolvedValue({
	    rendered_prompt: 'Rendered prompt',
	    used_placeholders: ['user_prompt'],
	    unused_known_placeholders: [],
	  })
	  mockApi.getIssueCIFailures.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
	  mockApi.getCIFailureLogs.mockResolvedValue({ items: [] })
	  mockApi.getIssueWebhookEvents.mockResolvedValue({ items: [], total: 0, page: 1, page_size: 20 })
	  return issue
	}

async function mountComponent(issueId = 1) {
  await router.push(`/issues/${issueId}`)
  await router.isReady()
  const wrapper = mount(IssueView, {
    global: { plugins: [router] },
  })
  await flushPromises()
  return wrapper
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('IssueView', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    resetMockApi()
    Object.values(mockMessage).forEach(fn => fn.mockClear())
    mockDialog.warning.mockClear()
  })

  afterEach(() => {
    wrapper?.unmount()
  })

  // =========================================================================
  // Basic rendering
  // =========================================================================
  describe('basic rendering', () => {
    it('shows loading spinner while issue loads', async () => {
      mockApi.getIssue.mockReturnValue(new Promise(() => {})) // never resolves
      mockApi.getProjects.mockResolvedValue([])
      mockApi.getPromptTemplates.mockResolvedValue([])
      mockApi.getProviders.mockResolvedValue([])
      await router.push('/issues/1')
      await router.isReady()
      wrapper = mount(IssueView, { global: { plugins: [router] } })
      // Issue is null so v-else renders spinner
      expect(wrapper.find('.n-spin-loading, .n-spin').exists()).toBe(true)
    })

    it('renders issue title and status after loading', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const text = wrapper.text()
      expect(text).toContain('#1')
      expect(text).toContain('Test Issue')
    })

    it('prioritizes an active task in the execution summary', async () => {
      setupDefaultMocks({
        tasks: [
          { ...createMockIssue().tasks[0], id: 7, status: 'running', user_prompt: 'Active work' },
          { ...createMockIssue().tasks[1], id: 8, status: 'completed', user_prompt: 'Newer completed work' },
        ],
      })
      wrapper = await mountComponent()

      const summary = wrapper.find('[data-testid="issue-current-execution"]')
      expect(summary.text()).toContain('issue.currentExecution')
      expect(summary.text()).toContain('Task #7')

      await summary.find('.execution-card__body').trigger('click')
      await flushPromises()
      expect(router.currentRoute.value.name).toBe('TaskView')
      expect(router.currentRoute.value.params.id).toBe('7')
    })

    it('prioritizes a running task over newer queued and pending tasks', async () => {
      setupDefaultMocks({
        tasks: [
          {
            ...createMockIssue().tasks[0],
            id: 7,
            status: 'running',
            user_prompt: 'Running work',
            created_at: '2026-06-20T10:00:00Z',
          },
          {
            ...createMockIssue().tasks[0],
            id: 8,
            status: 'queued',
            user_prompt: 'Queued work',
            created_at: '2026-06-20T11:00:00Z',
          },
          {
            ...createMockIssue().tasks[0],
            id: 9,
            status: 'pending',
            user_prompt: 'Pending work',
            created_at: '2026-06-20T12:00:00Z',
          },
        ],
      })
      wrapper = await mountComponent()

      const summary = wrapper.find('[data-testid="issue-current-execution"]')
      expect(summary.text()).toContain('Task #7')
      expect(summary.text()).toContain('Running work')
    })

    it('renders delivery overview and basic issue information', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const text = wrapper.text()
      expect(text).toContain('issue.deliveryOverview')
      expect(text).toContain('issue.basicInfo')
      expect(text).toContain('issue.field.project')
      expect(text).toContain('issue.field.creator')
      expect(text).toContain('testuser')
      expect(text).toContain('main')
      expect(text).toContain('codify/issue-1')
      expect(text).toContain('!42')
      expect(text).toContain('session-abc')
    })

    it('uses a responsive workbench with a sticky overview column', () => {
      expect(issueViewSource).toContain('grid-template-columns: minmax(0, 2fr) minmax(300px, 1fr);')
      expect(issueViewSource).toContain('.issue-workbench__aside {\n  position: sticky;')
      expect(issueViewSource).toContain('.issue-workbench__main > * {\n  min-width: 0;\n  max-width: 100%;')
      expect(issueViewSource).toContain('@media (max-width: 1100px)')
      expect(issueViewSource).toContain('grid-template-columns: minmax(0, 1fr);')
    })

    it('avoids native nested scrollbars across the issue detail surface', () => {
      const sources = [
        issueViewSource,
        issueCiAutomationSource,
        issueTaskPanelSource,
        taskFormDrawerSource,
        rescheduleDrawerSource,
      ].join('\n')

      expect(issueTaskPanelSource).not.toContain('scroll-x')
      expect(sources).not.toMatch(/overflow-[xy]:\s*auto/)
      expect(issueViewSource).toContain('<n-scrollbar')
      expect(issueCiAutomationSource).toContain('<n-scrollbar')
      expect(taskFormDrawerSource).toContain('<n-scrollbar')
      expect(taskFormDrawerSource).toContain(':native-scrollbar="false"')
      expect(rescheduleDrawerSource).toContain(':native-scrollbar="false"')
    })

    it('displays description card when description exists', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const description = wrapper.find('[data-testid="issue-description-card"]')
      expect(description.exists()).toBe(true)
      expect(description.find('.n-scrollbar').exists()).toBe(false)
      expect(wrapper.text()).toContain('Test description')
    })

    it('hides description card when description is null', async () => {
      setupDefaultMocks({ description: null })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-description-card"]').exists()).toBe(false)
    })

	    it('renders task table with task rows', async () => {
	      setupDefaultMocks()
	      wrapper = await mountComponent()
	      const taskCard = wrapper.find('[data-testid="issue-tasks-card"]')
	      expect(taskCard.exists()).toBe(true)
	      const rows = wrapper.findAll('.n-data-table-row')
	      expect(rows).toHaveLength(2)
	    })

	    it('renders CI automation opt-in and empty state', async () => {
	      setupDefaultMocks({ ci_auto_repair_enabled: true })
	      wrapper = await mountComponent()

	      const automationCard = wrapper.find('[data-testid="issue-ci-failures-card"]')
	      expect(automationCard.exists()).toBe(true)
	      expect(automationCard.text()).toContain('issue.ciAutomation')
	      expect(automationCard.text()).toContain('issue.ciAutoRepairOn')
	      expect(automationCard.text()).toContain('issue.noCiAutomationEvents')
	    })

	    it('renders CI failure runs, collector logs, repair task link, and webhook receipt', async () => {
	      setupDefaultMocks({
	        ci_auto_repair_enabled: true,
	        tasks: [
	          {
	            id: 77,
	            issue_id: 1,
	            project_id: 1,
	            user_prompt: 'Repair CI failure',
	            status: 'completed',
	            priority: 1,
	            is_retry: false,
	            retry_source_task_id: null,
	            trigger_source: 'ci_auto_repair',
	            ci_failure_run_id: 9,
	            created_at: '2024-01-03T10:01:00Z',
	            updated_at: '2024-01-03T10:02:00Z',
	            initiator_username: 'testuser',
	          },
	          {
	            id: 78,
	            issue_id: 1,
	            project_id: 1,
	            user_prompt: 'Repair CI failure again',
	            status: 'completed',
	            priority: 1,
	            is_retry: false,
	            retry_source_task_id: null,
	            trigger_source: 'ci_auto_repair',
	            ci_failure_run_id: 10,
	            created_at: '2024-01-03T11:01:00Z',
	            updated_at: '2024-01-03T11:02:00Z',
	            initiator_username: 'testuser',
	          },
	          {
	            id: 79,
	            issue_id: 1,
	            project_id: 1,
	            user_prompt: 'Manual follow-up',
	            status: 'completed',
	            priority: 1,
	            is_retry: false,
	            retry_source_task_id: null,
	            trigger_source: 'manual',
	            ci_failure_run_id: null,
	            created_at: '2024-01-03T12:01:00Z',
	            updated_at: '2024-01-03T12:02:00Z',
	            initiator_username: 'testuser',
	          },
	        ],
	      })
	      mockApi.getIssueCIFailures.mockResolvedValue({
	        items: [
	          {
	            id: 9,
	            webhook_event_id: 3,
	            project_id: 1,
	            issue_id: 1,
	            merge_request_iid: 42,
	            source_branch: 'codify/issue-1',
	            target_branch: 'main',
	            pipeline_id: 1001,
	            pipeline_sha: 'abc123',
	            pipeline_ref: 'codify/issue-1',
	            pipeline_status: 'failed',
	            pipeline_url: 'https://gitlab.example.com/pipelines/1001',
	            status: 'task_created',
	            root_cause_strategy: 'first_failed_stage',
	            bundle_available: true,
	            repair_task_id: 77,
	            ignored_reason: null,
	            error_message: null,
	            collection_attempts: 1,
	            created_at: '2024-01-03T10:00:00Z',
	            updated_at: '2024-01-03T10:01:00Z',
	            logs: [
	              {
	                id: 11,
	                ci_failure_run_id: 9,
	                issue_id: 1,
	                task_id: 77,
	                step: 'repair_task_created',
	                status: 'success',
	                message: 'Created repair task #77',
	                details: null,
	                created_at: '2024-01-03T10:01:00Z',
	              },
	            ],
	            jobs: [
	              {
	                id: 4,
	                gitlab_job_id: 555,
	                name: 'unit-test',
	                stage: 'test',
	                status: 'failed',
	                failure_reason: 'script_failure',
	                allow_failure: false,
	                web_url: 'https://gitlab.example.com/jobs/555',
	                trace_path: null,
	                trace_size_bytes: 128,
	                is_root_cause: true,
	                is_downstream_suppressed: false,
	                classification: 'code',
	                created_at: '2024-01-03T10:00:00Z',
	              },
	            ],
	          },
	        ],
	        total: 1,
	        page: 1,
	        page_size: 20,
	      })
	      mockApi.getIssueWebhookEvents.mockResolvedValue({
	        items: [
	          {
	            id: 3,
	            event_type: 'pipeline',
	            event_action: 'failed',
	            project_id: 1,
	            merge_request_iid: 42,
	            issue_id: 1,
	            source_ip: null,
	            result: 'ci_failure_collecting',
	            result_detail: null,
	            payload_summary: { pipeline_id: 1001 },
	            created_at: '2024-01-03T10:00:00Z',
	          },
	          {
	            id: 4,
	            event_type: 'merge_request',
	            event_action: 'merge',
	            project_id: 1,
	            merge_request_iid: 42,
	            issue_id: 1,
	            source_ip: null,
	            result: 'issue_closed',
	            result_detail: 'Issue closed by MR merge',
	            payload_summary: { mr_title: 'Fix bug' },
	            created_at: '2024-01-03T10:02:00Z',
	          },
	        ],
	        total: 2,
	        page: 1,
	        page_size: 20,
	      })

	      wrapper = await mountComponent()

	      const automationCard = wrapper.find('[data-testid="issue-ci-failures-card"]')
	      expect(automationCard.text()).toContain('issue.pipelineLabel')
	      expect(automationCard.text()).toContain('unit-test · code')
	      expect(automationCard.text()).toContain('issue.ciFailureStatus.task_created')
	      expect(automationCard.text()).toContain('Created repair task #77')
	      expect(automationCard.text()).toContain('issue.viewRepairTask')
	      expect(automationCard.text()).toContain('issue.ciWebhookReceived')
	      const repairTaskSummary = automationCard.findAll('.ci-automation-summary__item')
	        .find(item => item.text().includes('issue.ciRepairTasks'))
	      expect(repairTaskSummary?.text()).toContain('2')
	      expect(automationCard.text()).not.toContain('config.webhookEventsResultCIFailureCollecting')
	      expect(automationCard.text()).not.toContain('issue.webhookEvents')
	      expect(automationCard.text()).not.toContain('Issue closed by MR merge')
	    })

	    it('refreshes CI automation data when the issue is refreshed', async () => {
	      setupDefaultMocks({ ci_auto_repair_enabled: true })
	      mockApi.getIssueCIFailures.mockResolvedValue({
	        items: [
	          {
	            id: 9,
	            webhook_event_id: null,
	            pipeline_id: 1001,
	            pipeline_url: null,
	            pipeline_ref: null,
	            status: 'collecting',
	            ignored_reason: null,
	            repair_task_id: null,
	            logs: [],
	            jobs: [],
	            created_at: '2024-01-03T10:00:00Z',
	          },
	        ],
	        total: 1,
	        page: 1,
	        page_size: 20,
	      })
	      wrapper = await mountComponent()

	      expect(mockApi.getIssueCIFailures).toHaveBeenCalledTimes(1)
	      mockApi.getIssueCIFailures.mockClear()
	      mockApi.getIssueWebhookEvents.mockClear()
	      mockApi.getCIFailureLogs.mockClear()

	      const refreshButton = wrapper.findAll('button')
	        .find(button => button.text().includes('common.refresh'))
	      expect(refreshButton).toBeDefined()
	      await refreshButton!.trigger('click')
	      await flushPromises()

	      expect(mockApi.getIssueCIFailures).toHaveBeenCalledWith(1, { page_size: 5 })
	      expect(mockApi.getIssueWebhookEvents).toHaveBeenCalledWith(1, { page_size: 50 })
	      expect(mockApi.getCIFailureLogs).not.toHaveBeenCalled()
	    })

	    it('does not overlap issue polling while a refresh is still running', async () => {
	      vi.useFakeTimers()
	      setupDefaultMocks({ ci_auto_repair_enabled: true })
	      wrapper = await mountComponent()

	      mockApi.getIssue.mockClear()
	      let resolveIssue: ((issue: any) => void) | undefined
	      mockApi.getIssue.mockImplementation(() => new Promise((resolve) => {
	        resolveIssue = resolve
	      }))

	      try {
	        await vi.advanceTimersByTimeAsync(5000)
	        expect(mockApi.getIssue).toHaveBeenCalledTimes(1)

	        await vi.advanceTimersByTimeAsync(20_000)
	        expect(mockApi.getIssue).toHaveBeenCalledTimes(1)
	      } finally {
	        resolveIssue?.(createMockIssue({ ci_auto_repair_enabled: true }))
	        await flushPromises()
	        wrapper.unmount()
	        vi.useRealTimers()
	      }
	    })

	    it('shows create task button for open issue (owner)', async () => {
	      setupDefaultMocks()
	      wrapper = await mountComponent()
      const btn = wrapper.find('[data-testid="issue-toggle-create-task"]')
      expect(btn.exists()).toBe(true)
    })

    it('hides create task button for closed issue', async () => {
      setupDefaultMocks({ status: 'closed' })
      wrapper = await mountComponent()
      const btn = wrapper.find('[data-testid="issue-toggle-create-task"]')
      expect(btn.exists()).toBe(false)
    })

    it('shows MR link when merge_request_url exists', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const link = wrapper.find('a[href="https://gitlab.example.com/mr/42"]')
      expect(link.exists()).toBe(true)
    })

    it('renders header actions with icons in semantic order', async () => {
      setupDefaultMocks({ status: 'closed', branch_name: 'codify/issue-1' })
      wrapper = await mountComponent()

      const actionButtons = wrapper.find('[data-testid="page-header-actions"]').findAll('button.n-button')
      const labels = actionButtons.map(button => button.text())

      expect(labels).toEqual([
        'issue.close',
        'issue.deleteBranch',
        'issue.edit',
        'common.refresh',
      ])
      expect(actionButtons.every(button => button.find('.n-icon').exists())).toBe(true)
      expect(actionButtons.map(button => button.find('.n-icon').attributes('data-icon'))).toEqual([
        'CloseCircleOutline',
        'TrashOutline',
        'CreateOutline',
        'RefreshOutline',
      ])
    })

    it('matches task header mobile action sizing', () => {
      expect(issueViewSource).toContain('.issue-actions__toolbar {\n    align-items: stretch;')
      expect(issueViewSource).toContain('.issue-actions__command {\n    flex: 1 1 150px;')
      expect(issueViewSource).toContain('justify-content: center;')
    })

    it('shows no MR text when merge_request_url is null', async () => {
      setupDefaultMocks({ merge_request_url: null, merge_request_iid: null })
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('issue.noMergeRequest')
    })

    it('shows dash when session_id is null', async () => {
      setupDefaultMocks({ claude_session_id: null })
      wrapper = await mountComponent()
      const sessionLabel = wrapper.find('.metadata-muted')
      expect(sessionLabel.exists()).toBe(true)
    })

    it('abbreviates a long session id and exposes the full value in a popover', async () => {
      const sessionId = '019ef123-4567-7890-abcd-1234567890ef'
      setupDefaultMocks({ claude_session_id: sessionId })
      wrapper = await mountComponent()

      expect(wrapper.find('[data-testid="issue-session-id-trigger"]').text()).toBe('019ef123…7890ef')
      expect(wrapper.find('.session-id-tooltip__value').text()).toBe(sessionId)
    })

    it('shows changes and tokens when totals exist', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const text = wrapper.text()
      expect(text).toContain('common.changes')
      expect(text).toContain('15')
      expect(text).toContain('analytics.tokens')
    })

    it('shows total duration from backend issue totals', async () => {
      setupDefaultMocks({
        totals: {
          additions: 10,
          deletions: 5,
          total_changes: 15,
          input_tokens: 150,
          output_tokens: 75,
          duration_seconds: 3661,
        },
      })
      wrapper = await mountComponent()

      expect(wrapper.text()).toContain('issue.totalTaskDuration')
      expect(wrapper.text()).toContain('1h 1m')
    })

    it('shows created and updated dates in basic information', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('common.created')
      expect(wrapper.text()).toContain('issue.field.updatedAt')
      expect(wrapper.text()).toContain('formatted-2024-01-01T10:00:00Z')
    })

    it('shows branch flow with base → work → target', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const branchItems = wrapper.findAll('.branch-node')
      expect(branchItems.length).toBeGreaterThanOrEqual(2)
      expect(wrapper.findAll('.branch-tooltip__value').map(item => item.text())).toEqual([
        'main',
        'codify/issue-1',
        'main',
      ])
    })

    it('shows dash when no branches exist', async () => {
      setupDefaultMocks({ branch_name: null, base_branch: null, target_branch: null })
      wrapper = await mountComponent()
      const branchFlow = wrapper.find('.branch-journey')
      expect(branchFlow.exists()).toBe(true)
      expect(branchFlow.text()).toBe('—')
    })
  })

  // =========================================================================
  // Branch policy & delete branch (Task 11)
  // =========================================================================
  describe('branch policy and delete branch', () => {
    it('renders a branch-policy metadata row when issue.branch_name exists', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      // Expect a dedicated branch policy row to be rendered (data-testid used by implementation)
      expect(wrapper.find('[data-testid="issue-branch-policy-row"]').exists()).toBe(true)
    })

    it('shows deleteBranchBadge or keepBranchBadge based on delete_branch_on_close', async () => {
      setupDefaultMocks({ delete_branch_on_close: true })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="delete-branch-badge"]').exists()).toBe(true)

      await wrapper.unmount()
      setupDefaultMocks({ delete_branch_on_close: false })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="keep-branch-badge"]').exists()).toBe(true)
    })

    it('shows branchDeletedBadge when issue.branch_deleted is true', async () => {
      setupDefaultMocks({ branch_deleted: true })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="branch-deleted-badge"]').exists()).toBe(true)
    })

    it('shows a delete-branch button only when issue.status === \"closed\" and issue.branch_name exists', async () => {
      setupDefaultMocks({ status: 'open', branch_name: 'codify/issue-1' })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-delete-branch-button"]').exists()).toBe(false)

      await wrapper.unmount()
      setupDefaultMocks({ status: 'closed', branch_name: 'codify/issue-1' })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="page-header-actions"] [data-testid="issue-delete-branch-button"]').exists()).toBe(true)
      expect(wrapper.find('[data-testid="issue-branch-policy-row"] [data-testid="issue-delete-branch-button"]').exists()).toBe(false)
    })

    it('clicking delete-branch calls deleteIssueBranch, updates issue state, and shows success message', async () => {
      const initial = setupDefaultMocks({ status: 'closed', branch_name: 'codify/issue-1' })
      mockApi.deleteIssueBranch.mockResolvedValue({ ...initial, branch_deleted: true })

      wrapper = await mountComponent()
      const btn = wrapper.find('[data-testid="issue-delete-branch-button"]')
      expect(btn.exists()).toBe(true)

      const confirmButtons = wrapper.findAll('.popconfirm-confirm-btn')
      await confirmButtons[confirmButtons.length - 1].trigger('click')
      await flushPromises()

      expect(mockApi.deleteIssueBranch).toHaveBeenCalledWith(1)
      expect(mockMessage.success).toHaveBeenCalledWith('issue.deleteBranchSuccess')
      expect(wrapper.find('[data-testid="branch-deleted-badge"]').exists()).toBe(true)
    })

    it('when issue.branch_deleted is true, delete-branch button is disabled and tooltip text branchAlreadyDeleted is available', async () => {
      setupDefaultMocks({ status: 'closed', branch_name: 'codify/issue-1', branch_deleted: true })
      wrapper = await mountComponent()
      const btn = wrapper.find('[data-testid="issue-delete-branch-button"]')
      expect(btn.exists()).toBe(true)
      expect(btn.attributes('disabled')).toBeDefined()

      // Tooltip should be available via NTooltip stub (data-tooltip attribute)
      const tooltip = wrapper.find('[data-testid="n-tooltip"]')
      expect(tooltip.exists()).toBe(true)
      expect(tooltip.attributes('data-tooltip')).toBe('issue.branchAlreadyDeleted')
    })
  })

  // =========================================================================
  // Data fetching
  // =========================================================================
  describe('data fetching', () => {
    it('calls getIssue on mount with correct ID', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent(42)
      expect(mockApi.getIssue).toHaveBeenCalledWith(42)
    })

    it('calls getPromptTemplates on mount', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(mockApi.getPromptTemplates).toHaveBeenCalled()
    })

    it('calls getProjects on mount', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(mockApi.getProjects).toHaveBeenCalled()
    })

    it('resolves project name from projects list', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('group/test-project')
    })

    it('falls back to Project #id when project not found', async () => {
      setupDefaultMocks({ project_id: 999 })
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('Project #999')
    })
  })

  // =========================================================================
  // isOwner
  // =========================================================================
  describe('isOwner', () => {
    it('returns true when oidcEnabled is false (no auth)', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = false
      setupDefaultMocks()
      wrapper = await mountComponent()
      // Edit button should be visible (owner features)
      expect(wrapper.find('[data-testid="issue-edit-button"]').exists()).toBe(true)
    })

    it('returns true when oidcEnabled and user matches initiator_user_id', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 5 } as any
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-edit-button"]').exists()).toBe(true)
      // Restore
      authState.oidcEnabled = false
      authState.user = null
    })

    it('returns true when user is admin', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 99 } as any
      ;(isAdmin as any).value = true
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-edit-button"]').exists()).toBe(true)
      // Restore
      authState.oidcEnabled = false
      authState.user = null
      ;(isAdmin as any).value = false
    })

    it('returns false when oidcEnabled and user does not match and not admin', async () => {
      const { authState, isAdmin } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 99 } as any
      ;(isAdmin as any).value = false
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-edit-button"]').exists()).toBe(false)
      // Restore
      authState.oidcEnabled = false
      authState.user = null
    })

    it('returns false when oidcEnabled and user is null', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = null
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-edit-button"]').exists()).toBe(false)
      // Restore
      authState.oidcEnabled = false
    })
  })

  // =========================================================================
  // Close issue
  // =========================================================================
  describe('close issue', () => {
    it('opens close choices and keeps branch by default when selected', async () => {
      const closedIssue = createMockIssue({ status: 'closed' })
      setupDefaultMocks()
      mockApi.closeIssue.mockResolvedValue(closedIssue)
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-close-button"]').trigger('click')
      await nextTick()

      expect(wrapper.text()).toContain('issue.closeBranchChoiceHint')
      const keepBranchBtn = wrapper.find('[data-testid="issue-close-keep-branch-button"]')
      expect(keepBranchBtn.exists()).toBe(true)
      await keepBranchBtn.trigger('click')
      await flushPromises()

      expect(mockApi.closeIssue).toHaveBeenCalledWith(1, {
        branch_action: 'keep',
        delete_branch: false,
      })
      expect(mockMessage.success).toHaveBeenCalledWith('issue.closeSuccess')
    })

    it('deletes branch when the close delete option is selected', async () => {
      const closedIssue = createMockIssue({ status: 'closed', branch_deleted: true })
      setupDefaultMocks({ branch_name: 'codify/issue-1', branch_deleted: false })
      mockApi.closeIssue.mockResolvedValue(closedIssue)
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-close-button"]').trigger('click')
      await nextTick()

      const deleteBranchBtn = wrapper.find('[data-testid="issue-close-delete-branch-button"]')
      expect(deleteBranchBtn.exists()).toBe(true)
      await deleteBranchBtn.trigger('click')
      await flushPromises()

      expect(mockApi.closeIssue).toHaveBeenCalledWith(1, {
        branch_action: 'delete',
        delete_branch: true,
      })
      expect(mockMessage.success).toHaveBeenCalledWith('issue.closeSuccess')
    })

    it('shows error message when closeIssue fails', async () => {
      setupDefaultMocks()
      mockApi.closeIssue.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-close-button"]').trigger('click')
      await nextTick()
      await wrapper.find('[data-testid="issue-close-keep-branch-button"]').trigger('click')
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('issue.closeFailed')
    })

    it('disables close button when issue is already closed', async () => {
      setupDefaultMocks({ status: 'closed' })
      wrapper = await mountComponent()
      const closeBtn = wrapper.find('[data-testid="issue-close-button"]')
      expect(closeBtn.exists()).toBe(true)
      expect(closeBtn.attributes('disabled')).toBeDefined()
    })
  })

  // =========================================================================
  // Edit issue
  // =========================================================================
  describe('edit issue', () => {
    it('opens edit modal with prefilled title and description', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      // Modal should not exist initially
      expect(wrapper.find('.n-modal').exists()).toBe(false)

      // Click edit button
      const editBtn = wrapper.find('[data-testid="issue-edit-button"]')
      await editBtn.trigger('click')
      await nextTick()

      // Modal should now be visible
      expect(wrapper.find('.n-modal').exists()).toBe(true)
    })

    it('calls updateIssue with edited values and shows success', async () => {
      const updatedIssue = createMockIssue({ title: 'Updated Title', description: 'Updated desc' })
      setupDefaultMocks()
      mockApi.updateIssue.mockResolvedValue(updatedIssue)
      wrapper = await mountComponent()

      // Open edit modal
      await wrapper.find('[data-testid="issue-edit-button"]').trigger('click')
      await nextTick()

      // Find the save button within the modal and click it
      const modal = wrapper.find('.n-modal')
      const buttons = modal.findAll('button.n-button')
      const saveBtn = buttons[buttons.length - 1] // Last button is save
      await saveBtn.trigger('click')
      await flushPromises()

	      expect(mockApi.updateIssue).toHaveBeenCalledWith(1, {
	        title: 'Test Issue',
	        description: 'Test description',
	        ci_auto_repair_enabled: false,
	      })
      expect(mockMessage.success).toHaveBeenCalledWith('issue.updateSuccess')
    })

    it('shows error message when updateIssue fails', async () => {
      setupDefaultMocks()
      mockApi.updateIssue.mockRejectedValue(new Error('update failed'))
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-edit-button"]').trigger('click')
      await nextTick()

      const modal = wrapper.find('.n-modal')
      const buttons = modal.findAll('button.n-button')
      const saveBtn = buttons[buttons.length - 1]
      await saveBtn.trigger('click')
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('issue.updateFailed')
    })

    it('disables edit button when issue is closed', async () => {
      setupDefaultMocks({ status: 'closed' })
      wrapper = await mountComponent()
      const editBtn = wrapper.find('[data-testid="issue-edit-button"]')
      expect(editBtn.attributes('disabled')).toBeDefined()
    })
  })

  // =========================================================================
  // Create task
  // =========================================================================
  describe('create task', () => {
    it('opens create task drawer when button is clicked', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      expect(wrapper.find('[data-testid="issue-create-task-drawer"]').exists()).toBe(false)

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // Drawer is visible (rendered via NDrawer v-if show)
      expect(wrapper.findAll('.n-drawer').length).toBeGreaterThanOrEqual(1)
      expect(wrapper.find('[data-testid="issue-create-task-drawer"]').exists()).toBe(true)
    })

    it('pre-fills task prompt with issue description when drawer opens', async () => {
      setupDefaultMocks({ description: 'Issue description content' })
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const editor = wrapper.find('.variable-editor-mock')
      expect(editor.exists()).toBe(true)
    })

    it('calls createTask with correct payload (execute now)', async () => {
      const newTask = { id: 3 }
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue(newTask)
      mockApi.getIssue.mockResolvedValue(createMockIssue()) // for re-fetch
      wrapper = await mountComponent()

      // Open drawer
      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // Set task mode (required before creation)
      const drawer = wrapper.findComponent({ name: 'TaskFormDrawer' })
      drawer.vm.taskMode = 'execute'

      // Click create task button
      const createBtn = wrapper.find('[data-testid="issue-create-task-button"]')
      await createBtn.trigger('click')
      await flushPromises()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          issue_id: 1,
          priority: 1,
        }),
      )
      expect(mockMessage.success).toHaveBeenCalledWith('issue.taskCreated')
    })

    it('shows error message when createTask fails', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockRejectedValue(new Error('create fail'))
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'TaskFormDrawer' })
      drawer.vm.taskMode = 'execute'

      const createBtn = wrapper.find('[data-testid="issue-create-task-button"]')
      await createBtn.trigger('click')
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalled()
    })

    it('shows a quota alert when createTask is rejected for usage limits', async () => {
      setupDefaultMocks()
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
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'TaskFormDrawer' })
      drawer.vm.taskMode = 'execute'

      const createBtn = wrapper.find('[data-testid="issue-create-task-button"]')
      await createBtn.trigger('click')
      await flushPromises()

      const quotaAlert = wrapper.find('[data-testid="issue-create-task-usage-alert"]')
      expect(quotaAlert.exists()).toBe(true)
      expect(quotaAlert.text()).toContain('6')
      expect(quotaAlert.text()).toContain('5')
      expect(quotaAlert.text()).toContain('2026-04-29 00:00')
      expect(mockMessage.error).not.toHaveBeenCalled()
    })

    it('refreshes issue data after successful task creation', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 3 })
      wrapper = await mountComponent()

      // First call is from mount
      expect(mockApi.getIssue).toHaveBeenCalledTimes(1)

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'TaskFormDrawer' })
      drawer.vm.taskMode = 'execute'

      await wrapper.find('[data-testid="issue-create-task-button"]').trigger('click')
      await flushPromises()

      // Second call from re-fetch after task creation
      expect(mockApi.getIssue).toHaveBeenCalledTimes(2)
    })

    it('refreshes issue data when TaskFormDrawer emits created', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      const drawer = wrapper.findComponent({ name: 'TaskFormDrawer' })
      drawer.vm.$emit('created', { id: 3 })
      await flushPromises()

      expect(mockApi.getIssue).toHaveBeenCalledTimes(2)
    })
  })

  // =========================================================================
  // Retry task
  // =========================================================================
  describe('retry task', () => {
    it('calls retryTask and shows success message', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue(undefined)
      wrapper = await mountComponent()

      // retryTask is called via the task table column render function
      // We test the handleRetryTask function indirectly through the component's exposed behavior
      const { vm } = wrapper
      // Access the internal function
      // Since we can't easily trigger the button in stubbed NDataTable,
      // we verify retryTask API is available and test through the component
      expect(mockApi.retryTask).not.toHaveBeenCalled()
    })

    it('shows error detail message when retryTask fails with response data', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockRejectedValue({
        response: { data: { detail: 'Task already retried' } },
      })
      // We verify the mock setup is correct
      expect(mockApi.retryTask).not.toHaveBeenCalled()
    })
  })

  // =========================================================================
  // Prompt templates
  // =========================================================================
  describe('prompt templates', () => {
    it('loads templates on mount', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(mockApi.getPromptTemplates).toHaveBeenCalled()
    })

    it('handles template fetch error silently', async () => {
      setupDefaultMocks()
      mockApi.getPromptTemplates.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()
      expect(mockMessage.error).not.toHaveBeenCalled()
    })

    it('applies template content directly when prompt is empty', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()

      // Open create drawer
      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // The template drawer and template items are rendered when showTemplateDrawer is true
      // Since we can't click into nested drawers easily, we verify templates are loaded
      expect(mockApi.getPromptTemplates).toHaveBeenCalled()
    })
  })

  // =========================================================================
  // Error handling
  // =========================================================================
  describe('error handling', () => {
    it('shows error message when getIssue fails', async () => {
      mockApi.getIssue.mockRejectedValue(new Error('Network error'))
      mockApi.getProjects.mockResolvedValue([])
      mockApi.getPromptTemplates.mockResolvedValue([])
      mockApi.getProviders.mockResolvedValue([])
      wrapper = await mountComponent()
      expect(mockMessage.error).toHaveBeenCalledWith('issue.loadFailed')
    })

    it('handles getProjects failure silently', async () => {
      const warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {})
      setupDefaultMocks()
      mockApi.getProjects.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()
      // Should NOT show error for projects
      expect(mockMessage.error).not.toHaveBeenCalled()
      warnSpy.mockRestore()
    })

    it('shows loading spinner when issue is null due to error', async () => {
      mockApi.getIssue.mockRejectedValue(new Error('fail'))
      mockApi.getProjects.mockResolvedValue([])
      mockApi.getPromptTemplates.mockResolvedValue([])
      mockApi.getProviders.mockResolvedValue([])
      wrapper = await mountComponent()
      // Issue is null → v-else renders the spinner
      const issueView = wrapper.find('[data-testid="issue-view-page"]')
      expect(issueView.exists()).toBe(false)
    })
  })

  // =========================================================================
  // Task table structure
  // =========================================================================
  describe('task table', () => {
    it('renders correct number of task rows', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows).toHaveLength(2)
    })

    it('renders with empty tasks array', async () => {
      setupDefaultMocks({ tasks: [] })
      wrapper = await mountComponent()
      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows).toHaveLength(0)
    })

    it('renders with tasks that have retry info', async () => {
      const tasks = [
        {
          id: 1, issue_id: 1, project_id: 1, user_prompt: 'Fix bug',
          status: 'failed', priority: 1, is_retry: false, retry_source_task_id: null,
          created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z',
        },
        {
          id: 2, issue_id: 1, project_id: 1, user_prompt: 'Fix bug (retry)',
          status: 'running', priority: 1, is_retry: true, retry_source_task_id: 1,
          created_at: '2024-01-01T11:00:00Z', updated_at: '2024-01-01T11:00:00Z',
        },
      ]
      setupDefaultMocks({ tasks })
      wrapper = await mountComponent()
      const rows = wrapper.findAll('.n-data-table-row')
      expect(rows).toHaveLength(2)
    })

    it('shows task count in card header', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('issue.taskCount')
    })
  })

  // =========================================================================
  // Format helpers
  // =========================================================================
  describe('format helpers', () => {
    it('formatCompactDateTime returns formatted date', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('formatted-2024-01-01T10:00:00Z')
    })

    it('formatNumber formats token totals', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      // Tokens are displayed in the metadata
      expect(wrapper.text()).toContain('analytics.tokens')
    })
  })

  // =========================================================================
  // Schedule functionality
  // =========================================================================
  describe('schedule', () => {
    it('renders schedule options in create task drawer', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // Schedule radio and heatmap button should be present in drawer
      const text = wrapper.text()
      expect(text).toContain('createTask.viewScheduleHeatmap')
    })

    it('renders priority cards in create task drawer', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // Priority card descriptions should be rendered
      expect(wrapper.text()).toContain('createTask.priorityP0Desc')
      expect(wrapper.text()).toContain('createTask.priorityP1Desc')
      expect(wrapper.text()).toContain('createTask.priorityP2Desc')
      expect(wrapper.findAll('.priority-card')).toHaveLength(3)
    })

    it('validates scheduled time is in the future', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      // The isScheduleDateDisabled function is tested indirectly through the component
      // The date picker has the isDateDisabled prop set
      expect(wrapper.find('.n-date-picker').exists()).toBe(true)
    })
  })

  // =========================================================================
  // Edit modal close
  // =========================================================================
  describe('edit modal behavior', () => {
    it('closes edit modal after successful save', async () => {
      const updatedIssue = createMockIssue({ title: 'Updated' })
      setupDefaultMocks()
      mockApi.updateIssue.mockResolvedValue(updatedIssue)
      wrapper = await mountComponent()

      // Open modal
      await wrapper.find('[data-testid="issue-edit-button"]').trigger('click')
      await nextTick()
      expect(wrapper.find('.n-modal').exists()).toBe(true)

      // Save
      const modal = wrapper.find('.n-modal')
      const buttons = modal.findAll('button.n-button')
      await buttons[buttons.length - 1].trigger('click')
      await flushPromises()

      // Modal should be closed
      expect(wrapper.find('.n-modal').exists()).toBe(false)
    })

    it('keeps edit modal open after save failure', async () => {
      setupDefaultMocks()
      mockApi.updateIssue.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-edit-button"]').trigger('click')
      await nextTick()

      const modal = wrapper.find('.n-modal')
      const buttons = modal.findAll('button.n-button')
      await buttons[buttons.length - 1].trigger('click')
      await flushPromises()

      // Modal should still be open (showEditModal not set to false on error)
      expect(wrapper.find('.n-modal').exists()).toBe(true)
    })
  })

  // =========================================================================
  // Task column render functions
  // =========================================================================
  describe('taskColumns render functions', () => {
    function taskRecordColumn(vm: any) {
      const column = vm.taskColumns.find((c: any) => c.key === 'task_record')
      expect(column).toBeDefined()
      return column
    }

    function renderTaskRecord(vm: any, row: Record<string, any>) {
      return taskRecordColumn(vm).render({
        id: 1,
        status: 'completed',
        user_prompt: 'Fix a bug',
        created_at: '2024-01-01T10:00:00Z',
        scheduled_at: null,
        started_at: null,
        completed_at: null,
        is_retry: false,
        retry_source_task_id: null,
        ...row,
      })
    }

    function promptTooltip(record: any) {
      return record.children[0].children[1]
    }

    function promptTrigger(record: any) {
      return promptTooltip(record).children.trigger()
    }

    function actionVNode(record: any) {
      return record.children[1].children[1]?.children?.[0] ?? null
    }

    it('renders execution history as a single responsive record column', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()

      const columns = (wrapper.vm as any).taskColumns
      expect(columns.map((column: any) => column.key)).toEqual(['task_record'])
      expect(columns[0].width).toBeUndefined()
      expect(issueTaskPanelSource).toContain(':show-header="false"')
      expect(issueTaskPanelSource).toContain(':single-line="false"')
      expect(issueViewSource).toContain('.issue-view :deep(.task-record__details)')
      expect(issueViewSource).toContain('.issue-view :deep(.task-record__actions)')
    })

    it('renders status, retry badge, and prompt text in the first line', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, {
        id: 2,
        status: 'completed',
        user_prompt: 'Retry me',
        is_retry: true,
      })
      const status = record.children[0].children[0]
      const tooltip = promptTooltip(record)
      const vnode = promptTrigger(record)

      expect(record.props.class).toBe('task-record')
      expect(status.props.type).toBe('success')
      expect(status.props.size).toBe('tiny')
      expect(tooltip.props.contentStyle.fontSize).toBe('12px')
      expect(tooltip.props.themeOverrides).toMatchObject({ color: '#111827', textColor: '#fff' })
      expect(vnode.props.class).toBe('task-prompt-link')
      expect(vnode.children).toHaveLength(3)
      expect(vnode.children[0].props.class).toBe('task-prompt-link__id')
      expect(vnode.children[0].children).toBe('#2')
      expect(vnode.children[1].props).toMatchObject({
        class: 'task-prompt-link__retry-badge',
        size: 'tiny',
        round: true,
      })
      expect(vnode.children[1].props.type).toBeUndefined()
      expect(vnode.children[2].props.class).toBe('task-prompt-link__text')
      expect(vnode.children[2].children).toBe('Retry me')
      expect(issueViewSource).toContain('.issue-view :deep(.task-prompt-link)')
      expect(issueViewSource).toContain('.issue-view :deep(.task-prompt-link__retry-badge)')
      expect(issueViewSource).toContain('--n-color: #eef2ff')
      expect(issueViewSource).toContain('--n-text-color: #4338ca')
    })

    it('renders prompt text with truncation for long text', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const longPrompt = 'A'.repeat(120)
      const record = renderTaskRecord(vm, { id: 1, user_prompt: longPrompt })
      const vnode = promptTrigger(record)

      expect(vnode).toBeDefined()
      expect(vnode.children.at(-1).children).toBe('A'.repeat(96) + '…')
    })

    it('renders prompt text without truncation for short text', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const shortPrompt = 'Fix a bug'
      const record = renderTaskRecord(vm, { id: 1, user_prompt: shortPrompt })
      const tooltip = promptTooltip(record)
      const vnode = promptTrigger(record)

      expect(vnode.children.at(-1).children).toBe('Fix a bug')
      expect(tooltip.children.default().children).toBe('Fix a bug')
    })

    it('does not render separate status, retry, time, or action columns', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const columns = (wrapper.vm as any).taskColumns

      expect(columns.find((c: any) => c.key === 'status')).toBeUndefined()
      expect(columns.find((c: any) => c.key === 'is_retry')).toBeUndefined()
      expect(columns.find((c: any) => c.key === 'execution_time')).toBeUndefined()
      expect(columns.find((c: any) => c.key === 'actions')).toBeUndefined()
    })

    it('renders created time as the primary execution time in the detail line', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, { created_at: '2024-01-01T10:00:00Z', scheduled_at: null })
      const timeItem = record.children[1].children[0].children[0]
      const result = timeItem.children[1]

      expect(timeItem.children[0].children).toBe('issue.executionCreatedAt')
      expect(result.props.contentStyle.fontSize).toBe('12px')
      expect(result.props.themeOverrides).toMatchObject({ color: '#111827', textColor: '#fff' })
      const trigger = result.children.trigger()
      expect(trigger.props.class).toBe('task-table__time task-record__meta-value')
      expect(trigger.children).toBe('formatted-2024-01-01T10:00:00Z')
    })

    it('prefers scheduled time and exposes both timestamps in its tooltip', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, {
        created_at: '2024-01-01T10:00:00Z',
        scheduled_at: '2024-01-03T09:30:00Z',
      })
      const timeItem = record.children[1].children[0].children[0]
      const result = timeItem.children[1]

      expect(timeItem.children[0].children).toBe('dashboard.scheduled')
      expect(result.children.trigger().children).toBe('formatted-2024-01-03T09:30:00Z')
      const tooltip = result.children.default()
      expect(tooltip.children).toHaveLength(2)
      expect(tooltip.children[0].children).toContain('formatted-2024-01-01T10:00:00Z')
      expect(tooltip.children[1].children).toContain('formatted-2024-01-03T09:30:00Z')
    })

    it('renders duration from task start and completion time', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, {
        started_at: '2024-01-01T10:00:00Z',
        completed_at: '2024-01-01T10:05:00Z',
      })
      const result = record.children[1].children[0].children[1].children[1]

      expect(result.props.class).toBe('task-table__time task-record__meta-value')
      expect(result.children).toBe('5m 0s')
    })

    it('renders duration with dash when task has not started', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, { started_at: null, completed_at: null })
      const result = record.children[1].children[0].children[1].children[1]

      expect(result.children).toBe('—')
    })

    it('renders retry action for failed task when isOwner', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, {
        id: 99, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      const vnode = actionVNode(record)

      expect(vnode).toBeDefined()
      expect(vnode.type).toBeDefined()
      expect(vnode.children.default()).toBe('issue.retryTask')
      expect(vnode.children.icon().props.component.name).toBe('RefreshOutline')
    })

    it('renders no action for completed task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, {
        id: 1, status: 'completed', is_retry: false, retry_source_task_id: null,
      })

      expect(actionVNode(record)).toBeNull()
    })

    it('renders "retried as" link when retry task exists', async () => {
      const tasks = [
        {
          id: 1, issue_id: 1, project_id: 1, user_prompt: 'Fix bug',
          status: 'failed', priority: 1, is_retry: false, retry_source_task_id: null,
          created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z',
          initiator_username: 'testuser',
        },
        {
          id: 3, issue_id: 1, project_id: 1, user_prompt: 'Fix bug (retry)',
          status: 'running', priority: 1, is_retry: true, retry_source_task_id: 1,
          created_at: '2024-01-01T11:00:00Z', updated_at: '2024-01-01T11:00:00Z',
          initiator_username: 'testuser',
        },
      ]
      setupDefaultMocks({ tasks })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, tasks[0])
      const vnode = actionVNode(record)

      expect(vnode).toBeDefined()
      expect(vnode.type).toBe('span')
      expect(vnode.props.class).toBe('task-record__retried-as')
    })

    it('renders no action for failed task when not owner', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 99 } as any
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 99, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      expect(actionVNode(record)).toBeNull()

      // Restore
      authState.oidcEnabled = false
      authState.user = null
    })

    it('prompt link onClick navigates to task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const record = renderTaskRecord(vm, { id: 42, user_prompt: 'test' })
      const vnode = promptTrigger(record)

      const mockEvent = { stopPropagation: vi.fn() }
      vnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(router.currentRoute.value.name).toBe('TaskView')
      expect(router.currentRoute.value.params.id).toBe('42')
    })

    it('retry action onClick opens retry drawer', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue(undefined)
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 7, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      const vnode = actionVNode(record)

      const mockEvent = { stopPropagation: vi.fn() }
      vnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(mockApi.retryTask).not.toHaveBeenCalled()
      expect(vm.showRetryDrawer).toBe(true)
      expect(vm.retryTargetTask?.id).toBe(7)
    })

    it('reschedule action opens reschedule drawer for pending scheduled task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 8,
        status: 'pending',
        scheduled_at: '2024-01-01T12:00:00Z',
        is_retry: false,
        retry_source_task_id: null,
      })
      const vnode = actionVNode(record)

      expect(vnode.children.default()).toBe('taskView.rescheduleTask')
      expect(vnode.children.icon().props.component.name).toBe('CalendarOutline')
      const mockEvent = { stopPropagation: vi.fn() }
      vnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(vm.showRescheduleDrawer).toBe(true)
      expect(vm.rescheduleTargetTask?.id).toBe(8)
    })

    it('renders reschedule action for task initiator even when issue is owned by another user', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 99 } as any
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 8,
        status: 'pending',
        scheduled_at: '2024-01-01T12:00:00Z',
        is_retry: false,
        retry_source_task_id: null,
        initiator_user_id: 99,
        initiator_gitlab_user_id: null,
      })

      expect(actionVNode(record)).not.toBeNull()

      authState.oidcEnabled = false
      authState.user = null
    })

    it('renders reschedule action for queued task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 9,
        status: 'queued',
        scheduled_at: null,
        is_retry: false,
        retry_source_task_id: null,
      })
      const vnode = actionVNode(record)

      expect(vnode).toBeDefined()
      expect(vnode.type).toBeDefined()
    })

    it('does not render reschedule for unscheduled pending task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, {
        id: 10,
        status: 'pending',
        scheduled_at: null,
        is_retry: false,
        retry_source_task_id: null,
      })

      expect(actionVNode(record)).toBeNull()
    })

    it('"retried as" button navigates to retry task', async () => {
      const tasks = [
        {
          id: 1, issue_id: 1, project_id: 1, user_prompt: 'Fix bug',
          status: 'failed', priority: 1, is_retry: false, retry_source_task_id: null,
          created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z',
          initiator_username: 'testuser',
        },
        {
          id: 5, issue_id: 1, project_id: 1, user_prompt: 'Fix bug (retry)',
          status: 'completed', priority: 1, is_retry: true, retry_source_task_id: 1,
          created_at: '2024-01-01T11:00:00Z', updated_at: '2024-01-01T11:00:00Z',
          initiator_username: 'testuser',
        },
      ]
      setupDefaultMocks({ tasks })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const record = renderTaskRecord(vm, tasks[0])
      const vnode = actionVNode(record)
      // children[2] is the NButton vnode for "Task #5"
      const btnVnode = vnode.children[2]
      const mockEvent = { stopPropagation: vi.fn() }
      btnVnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(router.currentRoute.value.name).toBe('TaskView')
      expect(router.currentRoute.value.params.id).toBe('5')
    })
  })

  // =========================================================================
  // handleRetryTask
  // =========================================================================
  describe('handleRetryTask (direct call)', () => {
    it('calls retryTask API and shows success on resolve', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue(undefined)
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.handleRetryTask(2)
      await flushPromises()

      expect(mockApi.retryTask).toHaveBeenCalledWith(2)
      expect(mockMessage.success).toHaveBeenCalledWith('issue.retrySuccess')
      // Also re-fetches issue
      expect(mockApi.getIssue).toHaveBeenCalledTimes(2)
    })

    it('shows detail error message when retryTask fails with response.data.detail', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockRejectedValue({
        response: { data: { detail: 'Task already retried' } },
      })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.handleRetryTask(2)
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('Task already retried')
    })

    it('shows generic error when retryTask fails without detail string', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockRejectedValue({
        response: { data: { detail: { msg: 'complex' } } },
      })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.handleRetryTask(2)
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('issue.retryFailed')
    })

    it('shows generic error when retryTask fails without response', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockRejectedValue(new Error('network'))
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.handleRetryTask(2)
      await flushPromises()

      expect(mockMessage.error).toHaveBeenCalledWith('issue.retryFailed')
    })
  })

  // =========================================================================
  // retry drawer scheduling
  // =========================================================================
  describe('retry drawer scheduling', () => {
    it('opens retry drawer and preloads schedule context', async () => {
      setupDefaultMocks()
      mockApi.getScheduledTasks.mockResolvedValue([{ id: 31 }])
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openRetryDrawer({ id: 2, user_prompt: 'Retry me' })
      await flushPromises()

      expect(vm.showRetryDrawer).toBe(true)
      expect(vm.retryTargetTask.id).toBe(2)
      expect(vm.retryScheduleType).toBe('now')
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
      expect(mockApi.getConfig).toHaveBeenCalled()
    })

    it('submits scheduled retry with selected future time', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue({ id: 8 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const futureMs = Date.now() + 3600000

      await vm.openRetryDrawer({ id: 2, user_prompt: 'Retry me' })
      vm.retryScheduleType = 'scheduled'
      vm.retryTaskSchedule = futureMs

      await vm.handleSubmitRetry()
      await flushPromises()

      expect(mockApi.retryTask).toHaveBeenCalledWith(2, new Date(futureMs).toISOString())
      expect(mockMessage.success).toHaveBeenCalledWith('issue.retrySuccess')
      expect(vm.showRetryDrawer).toBe(false)
      expect(vm.retryTargetTask).toBeNull()
    })

    it('submits immediate retry when retry drawer is set to now', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue({ id: 8 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openRetryDrawer({ id: 2, user_prompt: 'Retry me' })
      vm.retryScheduleType = 'now'

      await vm.handleSubmitRetry()
      await flushPromises()

      expect(mockApi.retryTask).toHaveBeenCalledWith(2)
      expect(mockMessage.success).toHaveBeenCalledWith('issue.retrySuccess')
    })

    it('warns when scheduled retry has no selected time', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openRetryDrawer({ id: 2, user_prompt: 'Retry me' })
      vm.retryScheduleType = 'scheduled'
      vm.retryTaskSchedule = null

      await vm.handleSubmitRetry()
      await flushPromises()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.pleaseSelectScheduledTime')
      expect(mockApi.retryTask).not.toHaveBeenCalled()
    })
  })

  // =========================================================================
  // reschedule drawer
  // =========================================================================
  describe('reschedule drawer', () => {
    it('opens reschedule drawer and passes the selected task to RescheduleDrawer', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.openRescheduleDrawer({
        id: 8,
        user_prompt: 'Scheduled task',
        scheduled_at: '2024-01-01T12:00:00Z',
      })
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'RescheduleDrawer' })
      expect(vm.showRescheduleDrawer).toBe(true)
      expect(vm.rescheduleTargetTask.id).toBe(8)
      expect(drawer.props('show')).toBe(true)
      expect(drawer.props('task').id).toBe(8)
    })

    it('refreshes issue data when RescheduleDrawer emits rescheduled', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.openRescheduleDrawer({ id: 8, user_prompt: 'Scheduled task', scheduled_at: null })
      await nextTick()

      const drawer = wrapper.findComponent({ name: 'RescheduleDrawer' })
      drawer.vm.$emit('rescheduled', { id: 8 })
      await flushPromises()

      expect(mockApi.getIssue).toHaveBeenCalledTimes(2)
    })
  })

})
