import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref } from 'vue'
import GitLabSettingsPanel from './GitLabSettingsPanel.vue'

// Mock API
const mockApi = {
  listGitLabProjectWebhookStatuses: vi.fn(),
  setupGitLabProjectWebhook: vi.fn(),
  testGitLabConfig: vi.fn(),
  invalidateProjectCache: vi.fn()
}

vi.mock('../../api', () => ({
  listGitLabProjectWebhookStatuses: (...args: any[]) => mockApi.listGitLabProjectWebhookStatuses(...args),
  setupGitLabProjectWebhook: (...args: any[]) => mockApi.setupGitLabProjectWebhook(...args),
  testGitLabConfig: (...args: any[]) => mockApi.testGitLabConfig(...args),
  invalidateProjectCache: (...args: any[]) => mockApi.invalidateProjectCache(...args)
}))

// Mock naive-ui components
vi.mock('naive-ui', () => ({
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
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: ['n-alert', `n-alert--${props.type}`] }, slots.default?.())
    }
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'bordered', 'pagination', 'scrollX', 'rowKey'],
    setup(props: any) {
      return () => h('div', { class: 'n-data-table' },
        props.data?.map((row: any) => h('div', { class: 'n-data-table-row', key: props.rowKey(row) }))
      )
    }
  },
  NSpin: {
    name: 'NSpin',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-spin-loading' }, slots.default?.()) : h('div', { class: 'n-spin' }, slots.default?.())
    }
  },
  NForm: {
    name: 'NForm',
    props: ['model', 'rules', 'labelPlacement'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form' }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label', 'path'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, [
        slots.default?.(),
        slots.feedback?.()
      ])
    }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
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
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'type'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        type: props.type || 'text',
        value: props.value,
        placeholder: props.placeholder,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    }
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'round', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
    }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('button', {
        class: ['n-button', props.type],
        disabled: props.disabled || props.loading,
        onClick: () => {}
      }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['size', 'wrap', 'justify'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    }
  },
  useMessage: () => ({
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn()
  })
}))

// Mock vue-i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

// Mock @vueuse/core
vi.mock('@vueuse/core', () => ({
  useWindowSize: () => ({
    width: ref(1200)
  })
}))

// Mock useConfigForm
const mockConfigForm = {
  formValue: ref({
    gitlab_url: 'https://gitlab.example.com',
    gitlab_bot_token_input: '',
    gitlab_bot_token_configured: true,
    gitlab_admin_token_input: '',
    gitlab_admin_token_configured: true,
    gitlab_webhook_secret_input: '',
    gitlab_webhook_secret_configured: false
  }),
  sectionSaving: {
    gitlab: false
  },
  isSectionDirty: vi.fn((_section: string) => false),
  handleSaveSection: vi.fn(),
  handleClearSecret: vi.fn(),
  buildGitlabSectionUpdate: vi.fn(() => ({
    gitlab_url: 'https://gitlab.example.com'
  }))
}

vi.mock('./useConfigForm', () => ({
  useConfigForm: () => mockConfigForm
}))

const mockWebhookStatuses = [
  {
    project_id: 1,
    project_name: 'test-project',
    project_path_with_namespace: 'group/test-project',
    status: 'configured',
    secret_mode: 'project' as const,
	    hook_id: 123,
	    note_events: true,
	    merge_requests_events: true,
	    pipeline_events: true,
	    enable_ssl_verification: true,
    status_detail: null,
    hook_url: 'https://gitlab.example.com/hooks/123',
    target_webhook_url: null
  },
  {
    project_id: 2,
    project_name: 'another-project',
    project_path_with_namespace: 'group/another-project',
    status: 'missing',
    secret_mode: 'none' as const,
	    hook_id: null,
	    note_events: null,
	    merge_requests_events: null,
	    pipeline_events: null,
	    enable_ssl_verification: null,
    status_detail: null,
    hook_url: null,
    target_webhook_url: null
  }
]

describe('GitLabSettingsPanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockConfigForm.isSectionDirty.mockReturnValue(false)
    mockApi.listGitLabProjectWebhookStatuses.mockResolvedValue(mockWebhookStatuses)
  })

  const mountComponent = () => {
    wrapper = mount(GitLabSettingsPanel, {
      global: {
        stubs: {
          // Stub all naive-ui components to simplify rendering
        }
      }
    })
    return wrapper
  }

  describe('basic rendering', () => {
    it('should render without errors', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('.n-card').exists()).toBe(true)
    })

    it('should have gitlab-settings card', () => {
      const wrapper = mountComponent()
      expect(wrapper.find('#gitlab-settings').exists()).toBe(true)
    })

    it('should render save and revert buttons', () => {
      const wrapper = mountComponent()
      const buttons = wrapper.findAll('.n-button')
      const buttonTexts = buttons.map(btn => btn.text())
      expect(buttonTexts.some(text => text.includes('config.saveChanges'))).toBe(true)
      expect(buttonTexts.some(text => text.includes('config.revertChanges'))).toBe(true)
    })

    it('should render test GitLab connection button', () => {
      const wrapper = mountComponent()
      const buttons = wrapper.findAll('.n-button')
      const buttonTexts = buttons.map(btn => btn.text())
      expect(buttonTexts.some(text => text.includes('config.testGitlabConnection'))).toBe(true)
    })
  })

  describe('fetchWebhookStatuses', () => {
    it('should return empty array when gitlab_url is empty', async () => {
      mockConfigForm.formValue.value.gitlab_url = ''
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchWebhookStatuses()
      expect(wrapper.vm.webhookStatuses).toEqual([])
      // Reset
      mockConfigForm.formValue.value.gitlab_url = 'https://gitlab.example.com'
    })

    it('should return empty array when admin token not configured', async () => {
      mockConfigForm.formValue.value.gitlab_admin_token_configured = false
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchWebhookStatuses()
      expect(wrapper.vm.webhookStatuses).toEqual([])
      // Reset
      mockConfigForm.formValue.value.gitlab_admin_token_configured = true
    })

    it('should call listGitLabProjectWebhookStatuses when conditions met', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchWebhookStatuses()
      expect(mockApi.listGitLabProjectWebhookStatuses).toHaveBeenCalledTimes(1)
    })

    it('should set webhookStatusLoading during fetch', async () => {
      mockApi.listGitLabProjectWebhookStatuses.mockImplementation(() =>
        new Promise(resolve => setTimeout(() => resolve(mockWebhookStatuses), 100))
      )
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      const fetchPromise = wrapper.vm.fetchWebhookStatuses()
      await vi.waitFor(() => {
        expect(wrapper.vm.webhookStatusLoading).toBe(true)
      })
      await fetchPromise
    })

    it('should handle fetch error', async () => {
      mockApi.listGitLabProjectWebhookStatuses.mockRejectedValue(new Error('API Error'))
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchWebhookStatuses()
      expect(wrapper.vm.webhookStatuses).toEqual([])
      expect(wrapper.vm.webhookStatusState?.type).toBe('error')
    })
  })

  describe('handleTestGitLab', () => {
    it('should call testGitLabConfig', async () => {
      mockApi.testGitLabConfig.mockResolvedValue({
        gitlab_url: 'https://gitlab.example.com',
        username: 'test-user',
        server_version: '15.0.0'
      })
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      await wrapper.vm.handleTestGitLab()

      expect(mockApi.testGitLabConfig).toHaveBeenCalled()
      expect(wrapper.vm.gitlabTestState?.type).toBe('success')
    })

    it('should handle test failure', async () => {
      mockApi.testGitLabConfig.mockRejectedValue(new Error('Connection failed'))
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      await wrapper.vm.handleTestGitLab()

      expect(wrapper.vm.gitlabTestState?.type).toBe('error')
    })
  })

  describe('handleInvalidateProjectCache', () => {
    it('should call invalidateProjectCache', async () => {
      mockApi.invalidateProjectCache.mockResolvedValue(undefined)
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      await wrapper.vm.handleInvalidateProjectCache()

      expect(mockApi.invalidateProjectCache).toHaveBeenCalledTimes(1)
    })
  })

  describe('handleSetupProjectWebhook', () => {
    it('should call setupGitLabProjectWebhook', async () => {
      mockApi.setupGitLabProjectWebhook.mockResolvedValue({
        project_id: 1,
        project_name: 'test-project',
        action: 'created',
        hook_id: 456
      })
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      wrapper.vm.webhookStatuses = [...mockWebhookStatuses]

      await wrapper.vm.handleSetupProjectWebhook(1)

      expect(mockApi.setupGitLabProjectWebhook).toHaveBeenCalledWith(1)
    })
  })

  describe('filteredWebhookStatuses', () => {
    it('should return all statuses when search is empty', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      wrapper.vm.webhookStatuses = [...mockWebhookStatuses]
      wrapper.vm.webhookSearch = ''

      expect(wrapper.vm.filteredWebhookStatuses).toHaveLength(2)
    })

    it('should filter by project name', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      wrapper.vm.webhookStatuses = [...mockWebhookStatuses]
      wrapper.vm.webhookSearch = 'test-project'

      expect(wrapper.vm.filteredWebhookStatuses).toHaveLength(1)
      expect(wrapper.vm.filteredWebhookStatuses[0].project_name).toBe('test-project')
    })

    it('should filter by status', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      wrapper.vm.webhookStatuses = [...mockWebhookStatuses]
      wrapper.vm.webhookSearch = 'missing'

      expect(wrapper.vm.filteredWebhookStatuses).toHaveLength(1)
      expect(wrapper.vm.filteredWebhookStatuses[0].status).toBe('missing')
    })
  })

  describe('webhookSummaryItems', () => {
    it('should calculate correct summary', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      wrapper.vm.webhookStatuses = [...mockWebhookStatuses]

      const summary = wrapper.vm.webhookSummaryItems
      expect(summary[0].value).toBe('2') // total
      expect(summary[1].value).toBe('1') // configured
      expect(summary[2].value).toBe('0') // attention
      expect(summary[3].value).toBe('1') // missing/error
    })
  })

  describe('expose', () => {
    it('should expose fetchWebhookStatuses method', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        expect(typeof wrapper.vm.fetchWebhookStatuses).toBe('function')
      })
    })
  })
})
