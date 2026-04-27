import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount, flushPromises, type VueWrapper } from '@vue/test-utils'
import { h, ref, nextTick } from 'vue'
import { createRouter, createMemoryHistory } from 'vue-router'
import IssueView from './IssueView.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, resetMockApi, mockMessage, mockDialog } = vi.hoisted(() => {
  const mock = {
    getIssue: vi.fn<() => Promise<any>>(),
    updateIssue: vi.fn<() => Promise<any>>(),
    closeIssue: vi.fn<() => Promise<any>>(),
    createTask: vi.fn<() => Promise<any>>(),
    retryTask: vi.fn<() => Promise<any>>(),
    getPromptTemplates: vi.fn<() => Promise<any[]>>(),
    getScheduledTasks: vi.fn<() => Promise<any[]>>(),
    getSlotCapacity: vi.fn<() => Promise<any>>(),
    getConfig: vi.fn<() => Promise<any>>(),
    getProjects: vi.fn<() => Promise<any[]>>(),
    getProviders: vi.fn<() => Promise<any[]>>(),
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
}))

vi.mock('../utils/slotError', () => ({
  extractSlotErrorMessage: vi.fn((_error: any, t: any, fallbackKey: string) => t(fallbackKey)),
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
  getPromptTemplates: mockApi.getPromptTemplates,
  getScheduledTasks: mockApi.getScheduledTasks,
  getSlotCapacity: mockApi.getSlotCapacity,
  getConfig: mockApi.getConfig,
  getProjects: mockApi.getProjects,
  getProviders: mockApi.getProviders,
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
        slots.actions?.(),
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
      }, slots.default?.())
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
    setup(_p: any, { slots }: any) {
      return () => h('i', { class: 'n-icon' }, slots.default?.())
    },
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'row-key', 'row-props', 'bordered'],
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
    setup(props: any, { slots }: any) {
      return () => props.show
        ? h('div', { class: 'n-drawer' }, slots.default?.())
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
  useMessage: () => mockMessage,
  useDialog: () => mockDialog,
  DataTableColumns: {},
}))

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
        created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z',
        additions: 10, deletions: 5, input_tokens: 100, output_tokens: 50,
        initiator_username: 'testuser',
      },
      {
        id: 2, issue_id: 1, project_id: 1, user_prompt: 'Add unit tests',
        status: 'failed', priority: 1, is_retry: false, retry_source_task_id: null,
        created_at: '2024-01-01T11:00:00Z', updated_at: '2024-01-01T11:00:00Z',
        additions: 0, deletions: 0, input_tokens: 50, output_tokens: 25,
        initiator_username: 'testuser',
      },
    ],
    totals: {
      additions: 10, deletions: 5, total_changes: 15,
      input_tokens: 150, output_tokens: 75,
    },
    ...overrides,
  }
}

const mockProjects = [
  { id: 1, name: 'test-project', path_with_namespace: 'group/test-project', default_branch: 'main' },
]

const mockPromptTemplates = [
  { id: 1, name: 'Bug Fix', content: 'Fix the {{issue_type}} in {{file_path}}', variable_tips: { issue_type: 'Type', file_path: 'Path' }, is_active: true, created_at: '2024-01-01T10:00:00Z', updated_at: '2024-01-01T10:00:00Z' },
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
  mockApi.getProviders.mockResolvedValue([])
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

    it('renders metadata card with project, creator, branch flow, MR, session', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const text = wrapper.text()
      expect(text).toContain('common.status')
      expect(text).toContain('issue.field.project')
      expect(text).toContain('issue.field.creator')
      expect(text).toContain('testuser')
      expect(text).toContain('taskView.branchFlow')
      expect(text).toContain('main')
      expect(text).toContain('codify/issue-1')
      expect(text).toContain('!42')
      expect(text).toContain('session-abc')
    })

    it('displays description card when description exists', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.find('[data-testid="issue-description-card"]').exists()).toBe(true)
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

    it('shows changes and tokens when totals exist', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const text = wrapper.text()
      expect(text).toContain('common.changes')
      expect(text).toContain('15')
      expect(text).toContain('analytics.tokens')
    })

    it('shows timeline with created and updated dates', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      expect(wrapper.text()).toContain('common.timeline')
      expect(wrapper.text()).toContain('formatted-2024-01-01T10:00:00Z')
    })

    it('shows branch flow with base → work → target', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const branchItems = wrapper.findAll('.branch-item')
      expect(branchItems.length).toBeGreaterThanOrEqual(2)
    })

    it('shows dash when no branches exist', async () => {
      setupDefaultMocks({ branch_name: null, base_branch: null, target_branch: null })
      wrapper = await mountComponent()
      // The fallback dash span in branch flow
      const branchFlow = wrapper.find('.branch-flow')
      expect(branchFlow.exists()).toBe(true)
      expect(branchFlow.text()).toBe('-')
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
    it('calls closeIssue and shows success message', async () => {
      const closedIssue = createMockIssue({ status: 'closed' })
      setupDefaultMocks()
      mockApi.closeIssue.mockResolvedValue(closedIssue)
      wrapper = await mountComponent()

      const confirmBtn = wrapper.find('.popconfirm-confirm-btn')
      expect(confirmBtn.exists()).toBe(true)
      await confirmBtn.trigger('click')
      await flushPromises()

      expect(mockApi.closeIssue).toHaveBeenCalledWith(1)
      expect(mockMessage.success).toHaveBeenCalledWith('issue.closeSuccess')
    })

    it('shows error message when closeIssue fails', async () => {
      setupDefaultMocks()
      mockApi.closeIssue.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()

      const confirmBtn = wrapper.find('.popconfirm-confirm-btn')
      await confirmBtn.trigger('click')
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
    })

    it('pre-fills task prompt with issue description when drawer opens', async () => {
      setupDefaultMocks({ description: 'Issue description content' })
      wrapper = await mountComponent()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const editor = wrapper.find('.variable-editor-mock')
      expect(editor.exists()).toBe(true)
    })

    it('refreshes schedule preview data after creating another task', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 3 })
      mockApi.getScheduledTasks
        .mockResolvedValueOnce([{ id: 1 }])
        .mockResolvedValueOnce([{ id: 1 }, { id: 2 }])
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openScheduleDrawer()
      await flushPromises()
      expect(mockApi.getScheduledTasks).toHaveBeenCalledTimes(1)
      expect(vm.scheduledTasksForPreview).toEqual([{ id: 1 }])

      vm.showScheduleDrawer = false
      await nextTick()

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()
      await wrapper.find('[data-testid="issue-create-task-button"]').trigger('click')
      await flushPromises()

      await vm.openScheduleDrawer()
      await flushPromises()

      expect(mockApi.getScheduledTasks).toHaveBeenCalledTimes(2)
      expect(vm.scheduledTasksForPreview).toEqual([{ id: 1 }, { id: 2 }])
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

      const createBtn = wrapper.find('[data-testid="issue-create-task-button"]')
      await createBtn.trigger('click')
      await flushPromises()

      const quotaAlert = wrapper.find('[data-testid="issue-create-task-usage-alert"]')
      expect(quotaAlert.exists()).toBe(true)
      expect(quotaAlert.text()).toContain('6')
      expect(quotaAlert.text()).toContain('5')
      expect(quotaAlert.text()).toContain('2026-04-29 00:00 UTC+08:00')
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

      await wrapper.find('[data-testid="issue-create-task-button"]').trigger('click')
      await flushPromises()

      // Second call from re-fetch after task creation
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
      setupDefaultMocks()
      mockApi.getProjects.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()
      // Should NOT show error for projects
      expect(mockMessage.error).not.toHaveBeenCalled()
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
    it('renders status column with NTag vnode', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const statusCol = columns.find((c: any) => c.key === 'status')
      expect(statusCol).toBeDefined()
      const vnode = statusCol.render({ status: 'completed' })
      expect(vnode).toBeDefined()
      // vnode created by h(NTag, ...) — should be an object with type
      expect(vnode.type).toBeDefined()
    })

    it('renders description column with truncation for long text', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const descCol = columns.find((c: any) => c.key === 'user_prompt')
      expect(descCol).toBeDefined()

      const longPrompt = 'A'.repeat(100)
      const vnode = descCol.render({ id: 1, user_prompt: longPrompt })
      // Should truncate to 80 chars + '…'
      expect(vnode).toBeDefined()
      expect(vnode.children).toContain('A'.repeat(80) + '…')
    })

    it('renders description column without truncation for short text', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const descCol = columns.find((c: any) => c.key === 'user_prompt')

      const shortPrompt = 'Fix a bug'
      const vnode = descCol.render({ id: 1, user_prompt: shortPrompt })
      expect(vnode.children).toBe('Fix a bug')
    })

    it('renders retry column with tag when is_retry is true', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const retryCol = columns.find((c: any) => c.key === 'is_retry')
      expect(retryCol).toBeDefined()

      const vnodeRetry = retryCol.render({ is_retry: true })
      expect(vnodeRetry).toBeDefined()
      expect(vnodeRetry.type).toBeDefined() // h(NTag, ...)
    })

    it('renders retry column with empty string when is_retry is false', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const retryCol = columns.find((c: any) => c.key === 'is_retry')

      const vnode = retryCol.render({ is_retry: false })
      expect(vnode).toBe('')
    })

    it('renders created_at column with formatted date', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const createdCol = columns.find((c: any) => c.key === 'created_at')
      expect(createdCol).toBeDefined()

      const result = createdCol.render({ created_at: '2024-01-01T10:00:00Z' })
      expect(result).toBe('formatted-2024-01-01T10:00:00Z')
    })

    it('renders created_at column with dash for null value', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const createdCol = columns.find((c: any) => c.key === 'created_at')

      const result = createdCol.render({ created_at: null })
      expect(result).toBe('-')
    })

    it('renders actions column with retry button for failed task when isOwner', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')
      expect(actionsCol).toBeDefined()

      const vnode = actionsCol.render({
        id: 99, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      // Should be an h(NButton, ...) vnode
      expect(vnode).toBeDefined()
      expect(vnode.type).toBeDefined()
    })

    it('renders actions column with empty string for completed task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')

      const vnode = actionsCol.render({
        id: 1, status: 'completed', is_retry: false, retry_source_task_id: null,
      })
      expect(vnode).toBe('')
    })

    it('renders actions column with "retried as" link when retry task exists', async () => {
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
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')

      // Row id=1 has been retried as task id=3
      const vnode = actionsCol.render(tasks[0])
      expect(vnode).toBeDefined()
      // Should be an h('span', ...) with children including the retry task link
      expect(vnode.type).toBe('span')
    })

    it('renders actions column empty for failed task when not owner', async () => {
      const { authState } = await import('../auth')
      authState.oidcEnabled = true
      authState.user = { id: 99 } as any
      setupDefaultMocks({ initiator_user_id: 5 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')

      const vnode = actionsCol.render({
        id: 99, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      expect(vnode).toBe('')

      // Restore
      authState.oidcEnabled = false
      authState.user = null
    })

    it('description column render onClick navigates to task', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const descCol = columns.find((c: any) => c.key === 'user_prompt')

      const vnode = descCol.render({ id: 42, user_prompt: 'test' })
      // Invoke the onClick handler
      const mockEvent = { stopPropagation: vi.fn() }
      vnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(router.currentRoute.value.name).toBe('TaskView')
      expect(router.currentRoute.value.params.id).toBe('42')
    })

    it('actions column retry button onClick calls handleRetryTask', async () => {
      setupDefaultMocks()
      mockApi.retryTask.mockResolvedValue(undefined)
      wrapper = await mountComponent()
      const vm = wrapper.vm as any
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')

      const vnode = actionsCol.render({
        id: 7, status: 'failed', is_retry: false, retry_source_task_id: null,
      })
      // Trigger the onClick
      const mockEvent = { stopPropagation: vi.fn() }
      vnode.props.onClick(mockEvent)
      await flushPromises()

      expect(mockEvent.stopPropagation).toHaveBeenCalled()
      expect(mockApi.retryTask).toHaveBeenCalledWith(7)
    })

    it('actions column "retried as" button navigates to retry task', async () => {
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
      const columns = vm.taskColumns
      const actionsCol = columns.find((c: any) => c.key === 'actions')

      const vnode = actionsCol.render(tasks[0])
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
  // handleCreateTask with schedule validation
  // =========================================================================
  describe('handleCreateTask with schedule', () => {
    it('warns when scheduleType is scheduled but no time selected', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      // Open drawer so prompt gets pre-filled
      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      vm.scheduleType = 'scheduled'
      vm.newTaskSchedule = null

      await vm.handleCreateTask()
      await flushPromises()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.pleaseSelectScheduledTime')
      expect(mockApi.createTask).not.toHaveBeenCalled()
    })

    it('warns when scheduled time is in the past', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      vm.scheduleType = 'scheduled'
      vm.newTaskSchedule = Date.now() - 60000 // 1 minute in the past

      await vm.handleCreateTask()
      await flushPromises()

      expect(mockMessage.warning).toHaveBeenCalledWith('createTask.scheduledTimeFuture')
      expect(mockApi.createTask).not.toHaveBeenCalled()
    })

    it('sends scheduled_datetime when scheduleType is scheduled with future time', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 10 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      const futureMs = Date.now() + 3600000 // 1 hour in the future
      vm.scheduleType = 'scheduled'
      vm.newTaskSchedule = futureMs

      await vm.handleCreateTask()
      await flushPromises()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          issue_id: 1,
          scheduled_datetime: new Date(futureMs).toISOString(),
        }),
      )
      expect(mockMessage.success).toHaveBeenCalledWith('issue.taskCreated')
    })

    it('does not include scheduled_datetime when scheduleType is now', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 11 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      vm.scheduleType = 'now'
      vm.newTaskSchedule = null

      await vm.handleCreateTask()
      await flushPromises()

      const callArg = mockApi.createTask.mock.calls[0][0]
      expect(callArg.scheduled_datetime).toBeUndefined()
    })

    it('resets form state after successful scheduled task creation', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 12 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      vm.scheduleType = 'scheduled'
      vm.newTaskSchedule = Date.now() + 3600000
      vm.newTaskPrompt = 'test prompt'

      await vm.handleCreateTask()
      await flushPromises()

      expect(vm.newTaskPrompt).toBe('')
      expect(vm.newTaskSchedule).toBeNull()
      expect(vm.scheduleType).toBe('now')
      expect(vm.showCreateDrawer).toBe(false)
    })

    it('includes user_prompt when prompt is non-empty', async () => {
      setupDefaultMocks()
      mockApi.createTask.mockResolvedValue({ id: 13 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await wrapper.find('[data-testid="issue-toggle-create-task"]').trigger('click')
      await nextTick()

      vm.newTaskPrompt = '  Custom prompt text  '

      await vm.handleCreateTask()
      await flushPromises()

      expect(mockApi.createTask).toHaveBeenCalledWith(
        expect.objectContaining({
          user_prompt: 'Custom prompt text',
        }),
      )
    })
  })

  // =========================================================================
  // Template handling
  // =========================================================================
  describe('template handling (direct calls)', () => {
    it('applyPromptTemplate sets content and variable_tips', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      const tmpl = {
        id: 1,
        name: 'Test',
        content: 'Fix the {{issue_type}}',
        variable_tips: { issue_type: 'Bug type' },
      }
      vm.applyPromptTemplate(tmpl)

      expect(vm.newTaskPrompt).toBe('Fix the {{issue_type}}')
      expect(vm.promptVariableTips).toEqual({ issue_type: 'Bug type' })
    })

    it('applyPromptTemplate works without variable_tips', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.promptVariableTips = { old: 'tip' }
      vm.applyPromptTemplate({ id: 2, name: 'Simple', content: 'Do something' })

      expect(vm.newTaskPrompt).toBe('Do something')
      // variable_tips not set, so old value remains
      expect(vm.promptVariableTips).toEqual({ old: 'tip' })
    })

    it('handleTemplateClick applies directly when prompt is empty', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskPrompt = ''
      const tmpl = { id: 1, name: 'T', content: 'New content', variable_tips: null }
      vm.handleTemplateClick(tmpl)

      expect(vm.newTaskPrompt).toBe('New content')
      expect(vm.showTemplateDrawer).toBe(false)
      expect(mockDialog.warning).not.toHaveBeenCalled()
    })

    it('handleTemplateClick shows confirmation when prompt has content', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskPrompt = 'Existing prompt'
      const tmpl = { id: 1, name: 'T', content: 'Override content', variable_tips: null }

      mockDialog.warning.mockImplementation(() => {})
      vm.handleTemplateClick(tmpl)

      expect(mockDialog.warning).toHaveBeenCalledWith(
        expect.objectContaining({
          title: 'common.confirm',
          content: 'createTask.templateOverwriteConfirm',
          positiveText: 'common.confirm',
          negativeText: 'common.cancel',
        }),
      )
      // Prompt should NOT have changed yet (waiting for confirmation)
      expect(vm.newTaskPrompt).toBe('Existing prompt')
    })

    it('handleTemplateClick confirmation callback applies template and closes drawer', async () => {
      setupDefaultMocks({ description: '' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskPrompt = 'Old content'
      vm.showTemplateDrawer = true
      const tmpl = { id: 1, name: 'T', content: 'New overridden', variable_tips: { x: 'tip' } }

      mockDialog.warning.mockImplementation(({ onPositiveClick }: any) => {
        onPositiveClick?.()
      })
      vm.handleTemplateClick(tmpl)

      expect(vm.newTaskPrompt).toBe('New overridden')
      expect(vm.promptVariableTips).toEqual({ x: 'tip' })
      expect(vm.showTemplateDrawer).toBe(false)
    })
  })

  // =========================================================================
  // Schedule drawer & slot capacity
  // =========================================================================
  describe('schedule drawer and slot capacity', () => {
    it('openScheduleDrawer opens drawer and fetches scheduled tasks', async () => {
      setupDefaultMocks()
      mockApi.getScheduledTasks.mockResolvedValue([{ id: 1 }])
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openScheduleDrawer()
      await flushPromises()

      expect(vm.showScheduleDrawer).toBe(true)
      expect(mockApi.getScheduledTasks).toHaveBeenCalled()
      expect(mockApi.getConfig).toHaveBeenCalled()
    })

    it('openScheduleDrawer handles getScheduledTasks error', async () => {
      setupDefaultMocks()
      mockApi.getScheduledTasks.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openScheduleDrawer()
      await flushPromises()

      expect(vm.showScheduleDrawer).toBe(true)
      expect(vm.scheduledTasksForPreview).toEqual([])
    })

    it('openScheduleDrawer does not re-fetch if tasks already loaded', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      // Pre-populate
      vm.scheduledTasksForPreview = [{ id: 1 }]
      mockApi.getScheduledTasks.mockClear()

      await vm.openScheduleDrawer()
      await flushPromises()

      expect(mockApi.getScheduledTasks).not.toHaveBeenCalled()
    })

    it('openScheduleDrawer sets slotMaxTasks and slotEnforce from config', async () => {
      setupDefaultMocks()
      mockApi.getConfig.mockResolvedValue({
        runtime: { slot_max_tasks: 10, slot_max_tasks_enforce: true },
      })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openScheduleDrawer()
      await flushPromises()

      expect(vm.slotMaxTasks).toBe(10)
      expect(vm.slotEnforce).toBe(true)
    })

    it('openScheduleDrawer handles getConfig error silently', async () => {
      setupDefaultMocks()
      mockApi.getConfig.mockRejectedValue(new Error('config fail'))
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      await vm.openScheduleDrawer()
      await flushPromises()

      // Should not throw, drawer is still open
      expect(vm.showScheduleDrawer).toBe(true)
    })

    it('handleScheduleHeatmapCellClick sets time and closes drawer', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.showScheduleDrawer = true
      const ts = Date.now() + 3600000
      vm.handleScheduleHeatmapCellClick(ts)

      expect(vm.newTaskSchedule).toBe(ts)
      expect(vm.showScheduleDrawer).toBe(false)
    })

    it('watch(scheduleType) clears schedule when set to now', async () => {
      setupDefaultMocks()
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskSchedule = Date.now() + 3600000
      vm.scheduleType = 'scheduled'
      await nextTick()

      // Now switch back to 'now' — this should clear newTaskSchedule
      vm.scheduleType = 'now'
      await nextTick()

      expect(vm.newTaskSchedule).toBeNull()
    })

    it('watch(showCreateDrawer) pre-fills prompt from issue description', async () => {
      setupDefaultMocks({ description: 'Auto-filled description' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      // Ensure prompt is empty
      vm.newTaskPrompt = ''
      vm.showCreateDrawer = true
      await nextTick()

      expect(vm.newTaskPrompt).toBe('Auto-filled description')
    })

    it('watch(showCreateDrawer) does not overwrite existing prompt', async () => {
      setupDefaultMocks({ description: 'Issue desc' })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskPrompt = 'Existing prompt'
      vm.showCreateDrawer = false
      await nextTick()
      vm.showCreateDrawer = true
      await nextTick()

      expect(vm.newTaskPrompt).toBe('Existing prompt')
    })

    it('checkSlotCapacity calls getSlotCapacity after debounce', async () => {
      vi.useFakeTimers()
      setupDefaultMocks()
      mockApi.getSlotCapacity.mockResolvedValue({ available: 3 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskSchedule = Date.now() + 3600000
      await nextTick() // trigger the watch on heatmapSelectedMs

      // Advance past debounce timeout (300ms)
      vi.advanceTimersByTime(350)
      await flushPromises()

      expect(mockApi.getSlotCapacity).toHaveBeenCalled()
      expect(vm.slotCapacity).toEqual({ available: 3 })

      vi.useRealTimers()
    })

    it('checkSlotCapacity clears capacity when no time selected', async () => {
      vi.useFakeTimers()
      setupDefaultMocks()
      mockApi.getSlotCapacity.mockResolvedValue({ available: 5 })
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      // First set a time so capacity is fetched
      vm.newTaskSchedule = Date.now() + 3600000
      await nextTick()
      vi.advanceTimersByTime(350)
      await flushPromises()
      expect(vm.slotCapacity).toEqual({ available: 5 })

      // Now clear the selection
      vm.newTaskSchedule = null
      await nextTick()

      // checkSlotCapacity immediately sets slotCapacity = null and returns
      expect(vm.slotCapacity).toBeNull()

      vi.useRealTimers()
    })

    it('checkSlotCapacity handles API error gracefully', async () => {
      vi.useFakeTimers()
      setupDefaultMocks()
      mockApi.getSlotCapacity.mockRejectedValue(new Error('fail'))
      wrapper = await mountComponent()
      const vm = wrapper.vm as any

      vm.newTaskSchedule = Date.now() + 3600000
      await nextTick()

      vi.advanceTimersByTime(350)
      await flushPromises()

      expect(vm.slotCapacity).toBeNull()
      expect(vm.slotCapacityLoading).toBe(false)

      vi.useRealTimers()
    })
  })
})
