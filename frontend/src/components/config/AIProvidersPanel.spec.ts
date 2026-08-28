import { mount } from '@vue/test-utils'
import { vi, describe, it, expect, beforeEach } from 'vitest'

// Mock i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k })
}))

// Mock naive-ui: stub NDataTable (internal name 'DataTable') to avoid n-config-provider injection
vi.mock('naive-ui', async () => {
  const { h } = await import('vue')
  const actual = await vi.importActual<any>('naive-ui')
  return {
    ...actual,
    useMessage: () => ({ success: () => {}, error: () => {} }),
    NDataTable: {
      name: 'NDataTable',
      props: ['columns', 'data', 'loading', 'bordered', 'size', 'scroll-x'],
      setup: () => () => h('div', { class: 'n-data-table' })
    }
  }
})

import AIProvidersPanel from './AIProvidersPanel.vue'

// Hoisted mock API so vi.mock can reference the functions safely
const { mockApi, resetMockApi } = vi.hoisted(() => {
  const mock = {
    getProviders: vi.fn<() => Promise<any[]>>(() => Promise.resolve([])),
    createProvider: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    updateProvider: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    deleteProvider: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    setDefaultProvider: vi.fn<() => Promise<any>>(() => Promise.resolve())
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => {
      if (typeof fn.mock !== 'undefined') fn.mockReset()
    })
  }
  return { mockApi: mock, resetMockApi }
})

vi.mock('../../api', () => ({
  getProviders: mockApi.getProviders,
  createProvider: mockApi.createProvider,
  updateProvider: mockApi.updateProvider,
  deleteProvider: mockApi.deleteProvider,
  setDefaultProvider: mockApi.setDefaultProvider
}))

describe('AIProvidersPanel', () => {
  beforeEach(() => {
    resetMockApi()
  })

  it('opens create modal with empty form state', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    // Open create via component API
    // @ts-ignore
    await wrapper.vm.openCreate()

    // Expect modal state to be true
    // @ts-ignore
    expect(wrapper.vm.modalVisible).toBe(true)

    // form fields should be empty/default
    // @ts-ignore
    expect(wrapper.vm.formValue.name).toBe('')
    // max_turns default
    // @ts-ignore
    expect(wrapper.vm.formValue.max_turns).toBe(20)
  })

  it('resets edit state and validation when closing before create', async () => {
    const provider = {
      id: 'p1',
      name: 'provider1',
      base_url: 'https://api.example',
      model: 'model-x',
      max_turns: 50,
      api_key_configured: true,
      system_prompt: 'hello',
      is_default: false,
      is_disabled: false
    }

    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    const restoreValidation = vi.fn()
    // @ts-ignore
    wrapper.vm.formRef = { restoreValidation }

    // @ts-ignore
    await wrapper.vm.openEdit(provider)
    // @ts-ignore
    wrapper.vm.closeModal()
    // @ts-ignore
    await wrapper.vm.openCreate()

    // @ts-ignore
    expect(wrapper.vm.editingProvider).toBe(null)
    // @ts-ignore
    expect(wrapper.vm.formValue.name).toBe('')
    expect(restoreValidation).toHaveBeenCalled()
  })

  it('opens edit modal with provider values', async () => {
    const provider = {
      id: 'p1',
      name: 'provider1',
      base_url: 'https://api.example',
      model: 'model-x',
      max_turns: 50,
      api_key_configured: true,
      system_prompt: 'hello',
      is_default: false,
      is_disabled: true
    }

    mockApi.getProviders.mockResolvedValue([provider])

    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    // Simulate clicking edit button by invoking openEdit via component instance
    // @ts-ignore
    await wrapper.vm.openEdit(provider)

    // Expect modal state to be true
    // @ts-ignore
    expect(wrapper.vm.modalVisible).toBe(true)

    // formValue should be populated from provider (api_key empty)
    // @ts-ignore
    expect(wrapper.vm.formValue.name).toBe('provider1')
    // @ts-ignore
    expect(wrapper.vm.formValue.max_turns).toBe(50)
    // @ts-ignore
    expect(wrapper.vm.editingProvider.id).toBe('p1')
    // @ts-ignore
    expect(wrapper.vm.formValue.is_disabled).toBe(true)
  })

  it('closes after successful save', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    // Open create
    // @ts-ignore
    await wrapper.vm.openCreate()

    // Provide a fake formRef with validate
    // @ts-ignore
    wrapper.vm.formRef = { validate: () => Promise.resolve() }

    // Set form values
    // @ts-ignore
    wrapper.vm.formValue.name = 'new'
    // @ts-ignore
    wrapper.vm.formValue.base_url = 'https://x'
    // @ts-ignore
    wrapper.vm.formValue.model = 'm'

    // Trigger save via component API
    // @ts-ignore
    await wrapper.vm.handleSave()

    // createProvider should have been called
    expect(mockApi.createProvider).toHaveBeenCalled()

    // modal should be closed
    // @ts-ignore
    expect(wrapper.vm.modalVisible).toBe(false)
    // @ts-ignore
    expect(wrapper.vm.editingProvider).toBe(null)
    // @ts-ignore
    expect(wrapper.vm.formValue.name).toBe('')
  })

  it('switches the wire protocol when the provider kind changes', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    await wrapper.vm.openCreate()
    expect(wrapper.vm.formValue.provider_kind).toBe('anthropic_compatible')
    expect(wrapper.vm.formValue.model_protocol).toBe('anthropic_messages')

    wrapper.vm.handleProviderKindChange('openai_compatible')
    expect(wrapper.vm.formValue.model_protocol).toBe('openai_responses')
    expect(wrapper.vm.wireProtocolOptions.map(option => option.value))
      .toEqual(['anthropic_messages', 'openai_responses', 'openai_chat_completions'])
  })

  it('makes Chat Completions selectable from the default provider kind', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    await wrapper.vm.openCreate()
    expect(wrapper.vm.wireProtocolOptions.map(option => option.value))
      .toEqual(['anthropic_messages', 'openai_responses', 'openai_chat_completions'])

    wrapper.vm.handleModelProtocolChange('openai_chat_completions')
    expect(wrapper.vm.formValue.model_protocol).toBe('openai_chat_completions')
    expect(wrapper.vm.formValue.provider_kind).toBe('openai_compatible')
  })

  it('keeps chat completions selectable for new and existing providers', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })
    const provider = {
      id: 'p1',
      name: 'legacy-openai',
      base_url: 'https://api.example',
      model: 'model-x',
      max_turns: 20,
      api_key_configured: true,
      system_prompt: null,
      provider_kind: 'openai_compatible',
      model_protocol: 'openai_chat_completions',
      is_default: false,
      is_disabled: false
    }

    await wrapper.vm.openEdit(provider)
    expect(wrapper.vm.formValue.model_protocol).toBe('openai_chat_completions')
    expect(wrapper.vm.wireProtocolOptions.map(option => option.value))
      .toEqual(['anthropic_messages', 'openai_responses', 'openai_chat_completions'])
  })

  it('creates an OpenAI-compatible provider for Codex', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    await wrapper.vm.openCreate()
    wrapper.vm.formRef = { validate: () => Promise.resolve() }
    wrapper.vm.formValue.name = 'ds-openai'
    wrapper.vm.formValue.base_url = 'https://api.deepseek.com'
    wrapper.vm.formValue.model = 'deepseek-v4-flash'
    wrapper.vm.handleProviderKindChange('openai_compatible')
    await wrapper.vm.handleSave()

    expect(mockApi.createProvider).toHaveBeenCalledWith(expect.objectContaining({
      provider_kind: 'openai_compatible',
      model_protocol: 'openai_responses'
    }))
  })

  it('restores provider kind and wire protocol when editing', async () => {
    const provider = {
      id: 'p1',
      name: 'ds-openai',
      base_url: 'https://api.deepseek.com',
      model: 'deepseek-v4-flash',
      max_turns: 20,
      api_key_configured: true,
      system_prompt: null,
      provider_kind: 'openai_compatible',
      model_protocol: 'openai_responses',
      is_default: false,
      is_disabled: false
    }
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    await wrapper.vm.openEdit(provider)
    expect(wrapper.vm.formValue.provider_kind).toBe('openai_compatible')
    expect(wrapper.vm.formValue.model_protocol).toBe('openai_responses')
  })

  it('disables actions that would violate provider status rules', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSelect', 'NSpace', 'NSwitch', 'NTag']
      }
    })

    // @ts-ignore
    const actionColumn = wrapper.vm.columns.find((column: any) => column.key === 'actions')
    const renderActions = (provider: any) => {
      const vnode = actionColumn.render(provider)
      return vnode.children.default()
    }

    const defaultProviderActions = renderActions({
      id: 1,
      name: 'default',
      base_url: 'https://api.example',
      model: 'model-a',
      max_turns: 20,
      api_key_configured: true,
      system_prompt: null,
      is_default: true,
      is_disabled: false
    })
    expect(defaultProviderActions[1].props.disabled).toBe(true)
    expect(defaultProviderActions[2].props.disabled).toBe(true)

    const disabledProviderActions = renderActions({
      id: 2,
      name: 'disabled',
      base_url: 'https://api.example',
      model: 'model-b',
      max_turns: 20,
      api_key_configured: true,
      system_prompt: null,
      is_default: false,
      is_disabled: true
    })
    expect(disabledProviderActions[1].props.disabled).toBe(false)
    expect(disabledProviderActions[2].props.disabled).toBe(true)
  })
})
