import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import WorkerSettingsPanel from './WorkerSettingsPanel.vue'

function createRuntimeConfig() {
  return {
    worker_workspace_retention_days: 14
  }
}

function createWorkerProfile(overrides: Record<string, any> = {}) {
  return {
    id: 1,
    name: 'Default Worker',
    description: null,
    enabled: true,
    is_default: true,
    image: 'codify-worker:latest',
    codegraph_enabled: false,
    volume_mounts: [
      {
        host_path: '/host/cache',
        container_path: '/container/cache',
        mode: 'rw'
      }
    ],
    environment_variables: [
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ],
    pre_script: 'echo pre',
    post_script: 'echo post',
    default_execute_run_instruction_template: 'Execute {{user_prompt}}',
    default_plan_run_instruction_template: 'Plan {{user_prompt}}',
    ci_auto_repair_run_instruction_template: 'Repair {{issue_title}}',
    created_at: '2026-06-25T00:00:00',
    updated_at: '2026-06-25T00:00:00',
    ...overrides
  }
}

const {
  mockGetConfig,
  mockGetBuiltIns,
  mockGetWorkerProfiles,
  mockUpdateConfig,
  mockUpdateWorkerProfile,
  mockCreateWorkerProfile,
  mockDuplicateWorkerProfile,
  mockSetDefaultWorkerProfile,
  mockDisableWorkerProfile,
  mockMessage
} = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockGetBuiltIns: vi.fn(),
  mockGetWorkerProfiles: vi.fn(),
  mockUpdateConfig: vi.fn(),
  mockUpdateWorkerProfile: vi.fn(),
  mockCreateWorkerProfile: vi.fn(),
  mockDuplicateWorkerProfile: vi.fn(),
  mockSetDefaultWorkerProfile: vi.fn(),
  mockDisableWorkerProfile: vi.fn(),
  mockMessage: {
    success: vi.fn(),
    error: vi.fn()
  }
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

vi.mock('naive-ui', () => ({
  useThemeVars: () => ({
    value: {
      cardColor: '#fff',
      popoverColor: '#fff',
      actionColor: '#f5f5f5',
      hoverColor: '#eee',
      codeColor: '#f5f5f5',
      borderColor: '#ddd',
      dividerColor: '#ddd',
      textColor1: '#111',
      textColor2: '#333',
      textColor3: '#666',
      primaryColor: '#18a058',
      boxShadow2: 'none',
      fontFamilyMono: 'monospace'
    }
  }),
  NAlert: {
    name: 'NAlert',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-alert' }, slots.default?.())
    }
  },
  NButton: {
    name: 'NButton',
    props: ['disabled', 'loading', 'type', 'secondary', 'quaternary', 'size'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () =>
        h(
          'button',
          {
            class: 'n-button',
            disabled: props.disabled || props.loading,
            onClick: () => emit('click')
          },
          slots.default?.()
        )
    }
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    }
  },
  NForm: {
    name: 'NForm',
    props: ['model', 'labelPlacement'],
    setup(_props: any, { slots }: any) {
      return () => h('form', { class: 'n-form' }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('label', { class: 'n-form-item', 'data-label': props.label }, [slots.default?.(), slots.feedback?.()])
    }
  },
  NGi: {
    name: 'NGi',
    props: ['span'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    }
  },
  NIcon: {
    name: 'NIcon',
    props: ['component', 'size'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: 'n-icon' }, [
        props.component ? h(props.component) : slots.default?.()
      ])
    }
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'type', 'placeholder', 'showPasswordOn', 'size'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input',
          type: props.type || 'text',
          value: props.value,
          placeholder: props.placeholder,
          onInput: (event: Event) => emit('update:value', (event.target as HTMLInputElement).value)
        })
    }
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'min', 'max'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input-number',
          type: 'number',
          value: props.value,
          min: props.min,
          max: props.max,
          onInput: (event: Event) =>
            emit('update:value', Number((event.target as HTMLInputElement).value))
        })
    }
  },
  NPopover: {
    name: 'NPopover',
    props: ['show'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-popover' }, [slots.trigger?.(), slots.default?.()])
    }
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'size'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h(
          'select',
          {
            class: 'n-select',
            value: props.value,
            onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value)
          },
          (props.options || []).map((option: any) =>
            h('option', { key: option.value, value: option.value }, option.label)
          )
        )
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['size', 'wrap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    }
  },
  NSpin: {
    name: 'NSpin',
    props: ['show'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-spin' }, slots.default?.())
    }
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-switch',
          type: 'checkbox',
          checked: props.value,
          onChange: (event: Event) =>
            emit('update:value', (event.target as HTMLInputElement).checked)
        })
    }
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'round', 'size', 'bordered'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
    }
  },
  useMessage: () => mockMessage
}))

vi.mock('../../api', () => ({
  getConfig: mockGetConfig,
  getRunInstructionTemplateBuiltIns: mockGetBuiltIns,
  getWorkerProfiles: mockGetWorkerProfiles,
  updateConfig: mockUpdateConfig,
  updateWorkerProfile: mockUpdateWorkerProfile,
  createWorkerProfile: mockCreateWorkerProfile,
  duplicateWorkerProfile: mockDuplicateWorkerProfile,
  setDefaultWorkerProfile: mockSetDefaultWorkerProfile,
  disableWorkerProfile: mockDisableWorkerProfile
}))

describe('WorkerSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
    mockGetWorkerProfiles.mockResolvedValue([createWorkerProfile()])
    mockGetBuiltIns.mockResolvedValue({
      execute: { content: 'Execute {{user_prompt}}', available_placeholders: ['user_prompt'] },
      plan: { content: 'Plan {{user_prompt}}', available_placeholders: ['user_prompt'] },
      ci_auto_repair: { content: 'Repair {{issue_title}}', available_placeholders: ['issue_title'] }
    })
    mockUpdateConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
    mockUpdateWorkerProfile.mockResolvedValue(createWorkerProfile())
    mockCreateWorkerProfile.mockResolvedValue(createWorkerProfile({ id: 2, name: 'Worker Profile 2' }))
    mockDuplicateWorkerProfile.mockResolvedValue(createWorkerProfile({ id: 2, name: 'Default Worker Copy' }))
    mockSetDefaultWorkerProfile.mockResolvedValue(createWorkerProfile())
    mockDisableWorkerProfile.mockResolvedValue(createWorkerProfile({ enabled: false }))
  })

  it('does not render the legacy AI provider redirect card in worker settings', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    expect(wrapper.text()).toContain('config.workerSettings')
    expect(mockGetWorkerProfiles).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Default Worker')
    expect((wrapper.vm as any).workerFormValue.image).toBe('codify-worker:latest')
    expect(wrapper.text()).not.toContain('config.aiProvider')
    expect(wrapper.text()).not.toContain('config.providers.movedNotice')
  })

  it('renders mounts and environment variables as compact table rows', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    expect(wrapper.findAll('.config-compact-table')).toHaveLength(2)
    expect(wrapper.findAll('.config-compact-row--mount')).toHaveLength(1)
    expect(wrapper.findAll('.config-compact-row--environment')).toHaveLength(2)
    expect(wrapper.find('.config-compact-row--mount .n-form-item').exists()).toBe(false)
    expect(wrapper.find('.config-compact-row--environment .n-form-item').exists()).toBe(false)
    expect(wrapper.text().match(/config\.environmentVariableSecretHint/g)).toHaveLength(1)
  })

  it('adds new mounts and environment variables at the top of each list', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    vm.addMount()
    vm.addEnvironmentVariable()

    expect(vm.workerFormValue.mounts[0]).toEqual({
      host_path: '',
      container_path: '',
      mode: 'ro'
    })
    expect(vm.workerFormValue.mounts[1].host_path).toBe('/host/cache')
    expect(vm.workerFormValue.environment_variables[0]).toEqual({
      key: '',
      value: '',
      is_secret: false,
      value_configured: false
    })
    expect(vm.workerFormValue.environment_variables[1].key).toBe('SECRET_TOKEN')
  })

  it('loads and saves worker custom scripts', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.worker_pre_script).toBe('echo pre')
    expect(vm.workerFormValue.worker_post_script).toBe('echo post')

    vm.workerFormValue.worker_pre_script = 'npm ci'
    vm.workerFormValue.worker_post_script = 'npm test'

    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        pre_script: 'npm ci',
        post_script: 'npm test'
      })
    )
  })

  it('loads and saves the CodeGraph toggle', async () => {
    mockGetWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({ codegraph_enabled: true })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.codegraph_enabled).toBe(true)

    vm.workerFormValue.codegraph_enabled = false
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        codegraph_enabled: false
      })
    )
  })

  it('loads and saves workspace retention days', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.worker_workspace_retention_days).toBe(14)
    expect(wrapper.text()).toContain('config.workerWorkspaceRetentionDays')
    expect(wrapper.find('.worker-profile-editor').text()).not.toContain(
      'config.workerWorkspaceRetentionDays'
    )

    vm.workerFormValue.worker_workspace_retention_days = 30
    await vm.handleSaveWorker()

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_workspace_retention_days: 30
      }
    })
  })

  it('opens a local worker profile draft without posting when create is clicked', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.handleCreateProfile()

    expect(mockCreateWorkerProfile).not.toHaveBeenCalled()
    expect(vm.selectedProfileId).toBe(null)
    expect(vm.workerFormValue.name).toBe('')
    expect(vm.workerFormValue.image).toBe('codify-worker:latest')
    expect(vm.workerFormValue.mounts).toEqual([])
    expect(vm.workerFormValue.environment_variables).toEqual([])
    expect(vm.workerFormValue.default_execute_run_instruction_template).toBe(
      'Execute {{user_prompt}}'
    )
  })

  it('posts a new worker profile only when saving a filled draft', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.handleCreateProfile()
    vm.workerFormValue.name = 'Java Worker'
    vm.workerFormValue.image = 'codify-worker-java:latest'

    mockCreateWorkerProfile.mockResolvedValueOnce(
      createWorkerProfile({
        id: 3,
        name: 'Java Worker',
        image: 'codify-worker-java:latest',
        volume_mounts: [],
        environment_variables: []
      })
    )

    await vm.handleSaveWorker()

    expect(mockCreateWorkerProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Java Worker',
        image: 'codify-worker-java:latest',
        codegraph_enabled: false,
        volume_mounts: [],
        environment_variables: []
      })
    )
    expect(mockUpdateWorkerProfile).not.toHaveBeenCalled()
    expect(vm.selectedProfileId).toBe(3)
  })

  it('does not save workspace retention days when worker profile save fails', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    mockUpdateWorkerProfile.mockRejectedValueOnce({
      response: { data: { detail: 'worker profile invalid' } }
    })

    const vm = wrapper.vm as any
    vm.workerFormValue.worker_workspace_retention_days = 30
    await vm.handleSaveWorker()

    expect(mockUpdateConfig).not.toHaveBeenCalled()
    expect(mockMessage.error).toHaveBeenCalledWith('worker profile invalid')
  })

  it('loads configured secret environment variables without exposing stored values', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any

    expect(vm.workerFormValue.environment_variables).toEqual([
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ])
    expect((wrapper.find('input[type="password"]').element as HTMLInputElement).value).toBe('')
    expect(wrapper.find('input[type="password"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('config.configured')
  })

  it('preserves configured secret environment variables when saved with blank values', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        environment_variables: [
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: '',
            is_secret: true
          },
          {
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false
          }
        ]
      })
    )
    expect(vm.workerFormValue.environment_variables).toEqual([
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ])
  })

  it('clears newly entered secret values from local state after save while keeping configured status', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    vm.workerFormValue.environment_variables[0].value = 'new-secret-value'
    vm.workerFormValue.environment_variables.push({
      key: 'NEW_SECRET',
      value: 'brand-new-secret',
      is_secret: true,
      value_configured: false
    })

    mockUpdateWorkerProfile.mockResolvedValueOnce(
      createWorkerProfile({
        environment_variables: [
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: '',
            is_secret: true,
            value_configured: true
          },
          {
            id: 19,
            key: 'NEW_SECRET',
            value: '',
            is_secret: true,
            value_configured: true
          },
          {
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false,
            value_configured: true
          }
        ]
      })
    )

    await vm.handleSaveWorker()

    expect(vm.workerFormValue.environment_variables).toEqual([
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 19,
        key: 'NEW_SECRET',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 19,
        key: 'NEW_SECRET',
        value: '',
        is_secret: true,
        value_configured: true
      },
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      }
    ])
    expect(wrapper.text()).toContain('config.configured')
    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        environment_variables: [
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: 'new-secret-value',
            is_secret: true
          },
          {
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false
          },
          {
            id: undefined,
            key: 'NEW_SECRET',
            value: 'brand-new-secret',
            is_secret: true
          }
        ]
      })
    )
  })

  it('loads, restores, and saves independent run instruction templates', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any
    expect(vm.workerFormValue.default_execute_run_instruction_template).toBe(
      'Execute {{user_prompt}}'
    )
    vm.workerFormValue.default_execute_run_instruction_template = 'Custom execute'
    vm.restoreBuiltIn('execute')
    expect(vm.workerFormValue.default_execute_run_instruction_template).toBe(
      'Execute {{user_prompt}}'
    )
    vm.workerFormValue.default_plan_run_instruction_template = 'Custom plan'
    await vm.handleSaveWorker()
    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        default_execute_run_instruction_template: 'Execute {{user_prompt}}',
        default_plan_run_instruction_template: 'Custom plan',
        ci_auto_repair_run_instruction_template: 'Repair {{issue_title}}'
      })
    )
  })
})
