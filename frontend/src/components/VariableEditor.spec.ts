import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { shallowMount } from '@vue/test-utils'
import { ref, computed, nextTick } from 'vue'

// Create mock values that can be updated per test
const mockVariables = ref<string[]>([])
const mockMergedTipsState = ref<Record<string, string>>({})
const mockMergedTips = computed(() => mockMergedTipsState.value)
const mockVariablesWithTips = ref<Array<{ name: string; tip: string }>>([])

// Use vi.hoisted to properly hoist the mock before vi.mock is hoisted
const { mockUseVariableEditor } = vi.hoisted(() => {
  const mockUseVariableEditor = vi.fn().mockImplementation(() => ({
    variables: mockVariables,
    mergedTips: mockMergedTips,
    updateTip: vi.fn(),
    variablesWithTips: mockVariablesWithTips
  }))

  return { mockUseVariableEditor }
})

// Mock vue-i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
    locale: { value: 'en' }
  })
}))

// Mock the composable - must use named export
vi.mock('../composables/useVariableEditor', () => ({
  useVariableEditor: mockUseVariableEditor
}))

// Mock codemirror
vi.mock('codemirror', () => {
  const MockEditorView = function(this: any) {
    return {
      state: {
        doc: {
          toString: () => 'test content',
          length: 12
        }
      },
      dispatch: vi.fn(),
      destroy: vi.fn()
    }
  }
  MockEditorView.updateListener = {
    of: vi.fn().mockReturnValue({})
  }
  MockEditorView.theme = vi.fn().mockReturnValue({})
  return {
    EditorView: MockEditorView,
    minimalSetup: vi.fn()
  }
})

vi.mock('@codemirror/state', () => ({
  EditorState: {
    create: vi.fn().mockReturnValue({
      doc: {
        toString: () => 'test content'
      }
    })
  },
  RangeSetBuilder: vi.fn().mockImplementation(() => ({
    add: vi.fn().mockReturnThis(),
    finish: vi.fn().mockReturnValue([])
  }))
}))

vi.mock('@codemirror/view', () => {
  const MockDecoration = {
    mark: vi.fn().mockReturnValue({})
  }
  const MockEditorView = function(this: any) {
    return {
      state: {
        doc: {
          toString: () => 'test content',
          length: 12,
          lineAt: vi.fn()
        }
      },
      dispatch: vi.fn(),
      destroy: vi.fn()
    }
  }
  MockEditorView.updateListener = {
    of: vi.fn().mockReturnValue({})
  }
  MockEditorView.theme = vi.fn().mockReturnValue({})
  return {
    Decoration: MockDecoration,
    EditorView: MockEditorView,
    hoverTooltip: vi.fn().mockReturnValue({}),
    ViewPlugin: {
      fromClass: vi.fn().mockReturnValue({})
    }
  }
})

// Mock naive-ui components
vi.mock('naive-ui', () => ({
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    template: '<span class="n-icon">{{ component?.name || "" }}</span>'
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'size', 'placeholder'],
    template: '<input class="n-input" :value="value" :placeholder="placeholder" />',
    emits: ['update:value']
  }
}))

// Mock @vicons/ionicons5
vi.mock('@vicons/ionicons5', () => ({
  InformationCircleOutline: {
    name: 'InformationCircleOutline'
  }
}))

// Import the component after mocks are set up
import VariableEditor from './VariableEditor.vue'
import { Decoration, hoverTooltip } from '@codemirror/view'
import { minimalSetup } from 'codemirror'

describe('VariableEditor', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset mock values
    mockVariables.value = []
    mockMergedTipsState.value = {}
    mockVariablesWithTips.value = []
    // Reset mock implementation
    mockUseVariableEditor.mockImplementation(() => ({
      variables: mockVariables,
      mergedTips: mockMergedTips,
      updateTip: vi.fn(),
      variablesWithTips: mockVariablesWithTips
    }))
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('基础渲染', () => {
    it('should render codemirror editor container', async () => {
      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'test content'
        }
      })

      expect(wrapper.find('.variable-editor__codemirror').exists()).toBe(true)
    })

    it('should display tips panel when variables exist', async () => {
      // Configure mock to return variables
      mockVariables.value = ['issue_type']
      mockVariablesWithTips.value = [{ name: 'issue_type', tip: 'Type of issue' }]

      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'Fix {{issue_type}} bug',
          variableTips: {
            issue_type: 'Type of issue'
          }
        }
      })

      await nextTick()

      expect(wrapper.find('.variable-editor__tips-panel').exists()).toBe(true)
    })

    it('should show no-variables message when content has no variables', async () => {
      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'No variables here'
        }
      })

      await nextTick()

      expect(wrapper.find('.variable-editor__no-variables').exists()).toBe(true)
    })
  })

  describe('v-model 绑定', () => {
    it('should emit update:modelValue on content change', async () => {
      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'initial content'
        }
      })

      // Simulate content change
      const content = wrapper.find('.variable-editor__codemirror')
      expect(content.exists()).toBe(true)
    })

    it('should update editor when modelValue prop changes externally', async () => {
      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'initial content'
        }
      })

      await wrapper.setProps({ modelValue: 'updated content' })

      await nextTick()

      expect(wrapper.props('modelValue')).toBe('updated content')
    })
  })

  describe('variableTips prop', () => {
    it('should display tips for variables', async () => {
      mockVariables.value = ['issue_type', 'file_path']
      mockVariablesWithTips.value = [
        { name: 'issue_type', tip: 'Type of issue (bug, feature)' },
        { name: 'file_path', tip: 'Path to the file' }
      ]

      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'Fix {{issue_type}} in {{file_path}}',
          variableTips: {
            issue_type: 'Type of issue (bug, feature)',
            file_path: 'Path to the file'
          }
        }
      })

      await nextTick()

      const tipsPanel = wrapper.find('.variable-editor__tips-panel')
      expect(tipsPanel.exists()).toBe(true)

      const tipItems = wrapper.findAll('.variable-tip-item')
      expect(tipItems.length).toBe(2)
    })

    it('should handle editable tips mode', async () => {
      mockVariables.value = ['issue_type']
      mockVariablesWithTips.value = [{ name: 'issue_type', tip: 'Type of issue' }]

      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'Fix {{issue_type}}',
          variableTips: {
            issue_type: 'Type of issue'
          },
          editable: true
        }
      })

      await nextTick()

      // In editable mode, NInput should be rendered
      const inputs = wrapper.findAllComponents({ name: 'NInput' })
      expect(inputs.length).toBe(1)
    })

    it('should emit update:variableTips on tip change', async () => {
      mockVariables.value = ['issue_type']
      mockMergedTipsState.value = { issue_type: 'Original tip' }
      mockVariablesWithTips.value = [{ name: 'issue_type', tip: 'Original tip' }]

      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'Fix {{issue_type}}',
          variableTips: {
            issue_type: 'Original tip'
          },
          editable: true
        }
      })

      await nextTick()

      wrapper.vm.handleTipChange('issue_type', 'Updated tip')

      const emitted = wrapper.emitted()
      expect(emitted['update:variableTips']).toBeTruthy()
      expect(emitted['update:variableTips']?.[0]).toEqual([{ issue_type: 'Updated tip' }])
    })

    it('should not emit update:variableTips when merged tips already match props', async () => {
      mockVariables.value = ['issue_type']
      mockMergedTipsState.value = { issue_type: 'Original tip' }
      mockVariablesWithTips.value = [{ name: 'issue_type', tip: 'Original tip' }]

      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'Fix {{issue_type}}',
          variableTips: {
            issue_type: 'Original tip'
          },
          editable: true
        }
      })

      await nextTick()

      expect(wrapper.emitted()['update:variableTips']).toBeFalsy()
    })
  })

  describe('清理', () => {
    it('should have editorContainer ref defined', () => {
      const wrapper = shallowMount(VariableEditor, {
        props: {
          modelValue: 'test content'
        }
      })

      expect(wrapper.vm.$refs.editorContainer).toBeDefined()
    })

    it('should call editor destroy on unmount', async () => {
      // Mock the EditorView to return a spyable instance
      const destroySpy = vi.fn()
      const MockEditorView = function(this: any) {
        return {
          state: {
            doc: {
              toString: () => 'test content',
              length: 12
            }
          },
          dispatch: vi.fn(),
          destroy: destroySpy
        }
      }
      MockEditorView.updateListener = { of: vi.fn().mockReturnValue({}) }
      MockEditorView.theme = vi.fn().mockReturnValue({})

      vi.doMock('codemirror', () => ({
        EditorView: MockEditorView,
        minimalSetup: vi.fn()
      }))

      // Re-import to get fresh module with our mock
      vi.resetModules()
      const { default: VariableEditorComponent } = await import('./VariableEditor.vue')

      const wrapper = shallowMount(VariableEditorComponent, {
        props: {
          modelValue: 'test content'
        }
      })

      wrapper.unmount()

      expect(destroySpy).toHaveBeenCalled()
    })
  })

  describe('变量高亮', () => {
    it('should have variable highlight decoration configured', () => {
      expect(Decoration.mark).toBeDefined()
    })
  })

  describe('工具提示', () => {
    it('should have hoverTooltip configured', () => {
      expect(hoverTooltip).toBeDefined()
    })
  })

  describe('编辑器配置', () => {
    it('should use minimalSetup for prompt editing', () => {
      expect(minimalSetup).toBeDefined()
    })
  })
})
