import { mount } from '@vue/test-utils'
import { vi, describe, it, expect, beforeEach } from 'vitest'

// Mock i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k })
}))

// Mock naive-ui's useMessage but keep actual components so stubs in mount work
vi.mock('naive-ui', async () => {
  const actual = await vi.importActual<any>('naive-ui')
  return {
    ...actual,
    useMessage: () => ({ success: () => {}, error: () => {} })
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
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSpace', 'NTag']
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
      is_default: false
    }

    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSpace', 'NTag']
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
      is_default: false
    }

    mockApi.getProviders.mockResolvedValue([provider])

    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSpace', 'NTag']
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
  })

  it('closes after successful save', async () => {
    const wrapper = mount(AIProvidersPanel, {
      props: { isMobile: false },
      global: {
        stubs: ['NCard', 'NButton', 'NDataTable', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NInputNumber', 'NPopconfirm', 'NSpace', 'NTag']
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
})
