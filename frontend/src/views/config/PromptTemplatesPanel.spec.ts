import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h } from 'vue'
import PromptTemplatesPanel from './PromptTemplatesPanel.vue'

// Mock VariableEditor
vi.mock('../../components/VariableEditor.vue', () => ({
  default: {
    name: 'VariableEditor',
    props: ['variableTips', 'editable'],
    setup() {
      return () => h('div', { class: 'variable-editor' }, 'VariableEditor')
    }
  }
}))

// Mock API
const mockApi = {
  getPromptTemplates: vi.fn(),
  createPromptTemplate: vi.fn(),
  updatePromptTemplate: vi.fn(),
  deletePromptTemplate: vi.fn()
}

vi.mock('../../api', () => ({
  getPromptTemplates: (...args: any[]) => mockApi.getPromptTemplates(...args),
  createPromptTemplate: (...args: any[]) => mockApi.createPromptTemplate(...args),
  updatePromptTemplate: (...args: any[]) => mockApi.updatePromptTemplate(...args),
  deletePromptTemplate: (...args: any[]) => mockApi.deletePromptTemplate(...args)
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
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'loading', 'rowKey', 'pagination', 'bordered'],
    setup(props: any) {
      return () => h('div', { class: 'n-data-table' },
        props.data?.map((row: any) => h('div', { class: 'n-data-table-row', key: row.id }))
      )
    }
  },
  NForm: {
    name: 'NForm',
    props: ['model', 'labelPlacement'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form' }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label', 'path'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, slots.default?.())
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
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    setup(props: any, { emit }: any) {
      return () => h('button', {
        class: 'n-switch',
        onClick: () => emit('update:value', !props.value)
      })
    }
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'round'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
    }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary'],
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

const mockTemplates = [
  {
    id: 1,
    name: 'Bug Fix Template',
    content: 'Fix the {{issue_type}} in {{file_path}}',
    variable_tips: { issue_type: 'Type of issue', file_path: 'Path to file' },
    is_active: true,
    created_at: '2026-03-31T10:00:00Z',
    updated_at: '2026-03-31T10:00:00Z'
  },
  {
    id: 2,
    name: 'Feature Template',
    content: 'Add {{feature_name}} feature',
    variable_tips: {},
    is_active: false,
    created_at: '2026-03-30T10:00:00Z',
    updated_at: '2026-03-30T10:00:00Z'
  }
]

describe('PromptTemplatesPanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockApi.getPromptTemplates.mockResolvedValue(mockTemplates)
  })

  const mountComponent = () => {
    wrapper = mount(PromptTemplatesPanel, {
      global: {
        stubs: {
          // Stub all naive-ui components to simplify rendering
        }
      }
    })
    return wrapper
  }

  describe('basic rendering', () => {
    it('should render without errors', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        expect(wrapper.find('.n-card').exists()).toBe(true)
      })
    })

    it('should have prompt-templates-settings card', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        expect(wrapper.find('#prompt-templates-settings').exists()).toBe(true)
      })
    })

    it('should have create button', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        const buttons = wrapper.findAll('.n-button')
        const buttonTexts = buttons.map(btn => btn.text())
        expect(buttonTexts.some(text => text.includes('config.createPromptTemplate'))).toBe(true)
      })
    })

    it('should show data table after loading', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        expect(wrapper.find('.n-data-table').exists()).toBe(true)
      })
    })
  })

  describe('fetchPromptTemplates', () => {
    it('should call getPromptTemplates when manually called', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchPromptTemplates()
      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1)
    })

    it('should set loading state while fetching', async () => {
      mockApi.getPromptTemplates.mockImplementation(() => new Promise(resolve => setTimeout(() => resolve(mockTemplates), 100)))
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      const fetchPromise = wrapper.vm.fetchPromptTemplates()
      await vi.waitFor(() => {
        expect(wrapper.vm.promptTemplatesLoading).toBe(true)
      })
      await fetchPromise
    })

    it('should handle fetch error', async () => {
      mockApi.getPromptTemplates.mockRejectedValue(new Error('API Error'))
      const wrapper = mountComponent()
      await vi.waitFor(() => {})
      await wrapper.vm.fetchPromptTemplates()
      await vi.waitFor(() => {
        expect(wrapper.vm.promptTemplatesLoading).toBe(false)
      })
    })
  })

  describe('handleCreatePromptTemplate', () => {
    it('should reset form and open inline editor', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      wrapper.vm.handleCreatePromptTemplate()

      expect(wrapper.vm.promptTemplateEditingId).toBeNull()
      expect(wrapper.vm.promptTemplateEditorVisible).toBe(true)
      expect(wrapper.vm.promptTemplateForm.name).toBe('')
      expect(wrapper.vm.promptTemplateForm.content).toBe('')
    })
  })

  describe('handleEditPromptTemplate', () => {
    it('should populate form with template data', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      const template = mockTemplates[0]
      wrapper.vm.handleEditPromptTemplate(template)

      expect(wrapper.vm.promptTemplateEditingId).toBe(template.id)
      expect(wrapper.vm.promptTemplateForm.name).toBe(template.name)
      expect(wrapper.vm.promptTemplateForm.content).toBe(template.content)
      expect(wrapper.vm.promptTemplateEditorVisible).toBe(true)
    })
  })

  describe('handleCancelPromptTemplateEditing', () => {
    it('should close editor and reset form state', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      wrapper.vm.handleCreatePromptTemplate()
      wrapper.vm.promptTemplateForm.name = 'Draft'
      wrapper.vm.promptTemplateForm.content = 'Draft content'

      wrapper.vm.handleCancelPromptTemplateEditing()

      expect(wrapper.vm.promptTemplateEditorVisible).toBe(false)
      expect(wrapper.vm.promptTemplateEditingId).toBeNull()
      expect(wrapper.vm.promptTemplateForm.name).toBe('')
      expect(wrapper.vm.promptTemplateForm.content).toBe('')
    })
  })

  describe('handleDeletePromptTemplate', () => {
    it('should call delete API and refresh', async () => {
      mockApi.deletePromptTemplate.mockResolvedValue(undefined)
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      // Reset call count to track only the refresh call
      ;(mockApi.getPromptTemplates as any).mockClear()

      await wrapper.vm.handleDeletePromptTemplate(1)

      expect(mockApi.deletePromptTemplate).toHaveBeenCalledWith(1)
      expect(mockApi.getPromptTemplates).toHaveBeenCalledTimes(1) // Refresh call after delete
    })
  })

  describe('handleSavePromptTemplate', () => {
    it('should call create API for new template', async () => {
      mockApi.createPromptTemplate.mockResolvedValue(mockTemplates[0])
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      wrapper.vm.handleCreatePromptTemplate()
      wrapper.vm.promptTemplateForm.name = 'New Template'
      wrapper.vm.promptTemplateForm.content = 'Test content'
      wrapper.vm.promptTemplateForm.is_active = true

      await wrapper.vm.handleSavePromptTemplate()

      expect(mockApi.createPromptTemplate).toHaveBeenCalled()
      expect(wrapper.vm.promptTemplateEditorVisible).toBe(false)
    })

    it('should call update API for existing template', async () => {
      mockApi.updatePromptTemplate.mockResolvedValue(mockTemplates[0])
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      const template = mockTemplates[0]
      wrapper.vm.handleEditPromptTemplate(template)
      wrapper.vm.promptTemplateForm.name = 'Updated Name'

      await wrapper.vm.handleSavePromptTemplate()

      expect(mockApi.updatePromptTemplate).toHaveBeenCalledWith(template.id, expect.any(Object))
      expect(wrapper.vm.promptTemplateEditorVisible).toBe(false)
    })

    it('should warn about invalid variable tips', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      wrapper.vm.handleCreatePromptTemplate()
      wrapper.vm.promptTemplateForm.name = 'Test'
      wrapper.vm.promptTemplateForm.content = 'Use {{var1}}'
      wrapper.vm.promptTemplateForm.variable_tips = { var2: 'unused tip' }

      await wrapper.vm.handleSavePromptTemplate()

      // Should show warning and not call API
      expect(mockApi.createPromptTemplate).not.toHaveBeenCalled()
    })
  })

  describe('expose', () => {
    it('should expose fetchPromptTemplates method', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {
        expect(typeof wrapper.vm.fetchPromptTemplates).toBe('function')
      })
    })
  })

  describe('inline editor rendering', () => {
    it('should render inline editor after create action', async () => {
      const wrapper = mountComponent()
      await vi.waitFor(() => {})

      wrapper.vm.handleCreatePromptTemplate()
      await wrapper.vm.$nextTick()

      expect(wrapper.find('[data-testid="prompt-template-editor"]').exists()).toBe(true)
    })
  })
})
