import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import WorkerSettingsPanel from './WorkerSettingsPanel.vue'

function createRuntimeConfig() {
  return {
    worker_workspace_host_path: '/opt/codify-workspaces',
    worker_workspace_retention_days: 14,
    worker_artifacts_max_total_bytes: 200 * 1024 * 1024,
    worker_artifacts_max_file_bytes: 100 * 1024 * 1024,
    worker_artifacts_max_entries: 5000,
    worker_runtime_archive_retention_days: 30
  }
}

function createWorkerProfile(overrides: Record<string, any> = {}) {
  return {
    id: 1,
    name: 'Default Worker',
    description: null,
    enabled: true,
    is_default: true,
    image: 'codify-worker/java21-maven:2026.07',
    worker_kit_source: 'profile',
    runtime_mode: 'baked_image',
    worker_kit_version: null,
    worker_kit_path: null,
    docker_host: null,
    docker_tls_ca: null,
    docker_tls_cert: null,
    docker_tls_key: null,
    codegraph_enabled: false,
    volume_mounts: [
      {
        host_path: '/host/cache',
        container_path: '/container/cache',
        mode: 'rw'
      }
    ],
    volume_mount_masks: [],
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
    default_skill_ids: [],
    pre_script: 'echo pre',
    post_script: 'echo post',
    default_execute_run_instruction_template: 'Execute {{user_prompt}}',
    default_plan_run_instruction_template: 'Plan {{user_prompt}}',
    ci_auto_repair_run_instruction_template: 'Repair {{issue_title}}',
    shared_revision: 3,
    runtime_verification: {
      verified_at: null,
      verified_runtime_configuration_digest: null,
      matches_current_input: false
    },
    runtime_readiness: {
      status: 'unknown',
      checked_at: null,
      ready_until: null
    },
    created_at: '2026-06-25T00:00:00',
    updated_at: '2026-06-25T00:00:00',
    ...overrides
  }
}

function createSharedConfiguration(overrides: Record<string, any> = {}) {
  return {
    id: 1,
    revision: 3,
    runtime_mode: 'mounted_kit',
    worker_kit_version: '0.4.0',
    worker_kit_path: '/opt/codify/worker-kits/0.4.0',
    volume_mounts: [],
    environment_variables: [],
    pre_script: 'echo shared pre',
    post_script: 'echo shared post',
    default_execute_run_instruction_template: 'Shared execute {{user_prompt}}',
    default_plan_run_instruction_template: 'Shared plan {{user_prompt}}',
    ci_auto_repair_run_instruction_template: 'Shared repair {{issue_title}}',
    created_at: '2026-08-14T00:00:00Z',
    updated_at: '2026-08-15T00:00:00Z',
    ...overrides
  }
}

const {
  mockGetConfig,
  mockGetBuiltIns,
  mockGetAdminWorkerProfiles,
  mockGetWorkerSharedConfiguration,
  mockGetAdminSkills,
  mockTestWorkerDockerConnection,
  mockUpdateConfig,
  mockUpdateWorkerProfile,
  mockUpdateWorkerSharedConfiguration,
  mockVerifyWorkerProfileRuntime,
  mockCreateWorkerProfile,
  mockDeleteWorkerProfile,
  mockDuplicateWorkerProfile,
  mockEnableWorkerProfile,
  mockSetDefaultWorkerProfile,
  mockDisableWorkerProfile,
  mockMessage
} = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockGetBuiltIns: vi.fn(),
  mockGetAdminWorkerProfiles: vi.fn(),
  mockGetWorkerSharedConfiguration: vi.fn(),
  mockGetAdminSkills: vi.fn(),
  mockTestWorkerDockerConnection: vi.fn(),
  mockUpdateConfig: vi.fn(),
  mockUpdateWorkerProfile: vi.fn(),
  mockUpdateWorkerSharedConfiguration: vi.fn(),
  mockVerifyWorkerProfileRuntime: vi.fn(),
  mockCreateWorkerProfile: vi.fn(),
  mockDeleteWorkerProfile: vi.fn(),
  mockDuplicateWorkerProfile: vi.fn(),
  mockEnableWorkerProfile: vi.fn(),
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
    props: ['value', 'type', 'placeholder', 'showPasswordOn', 'size', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input',
          type: props.type || 'text',
          value: props.value,
          placeholder: props.placeholder,
          disabled: props.disabled,
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
  NPopconfirm: {
    name: 'NPopconfirm',
    props: ['positiveText', 'negativeText'],
    emits: ['positive-click'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-popconfirm' }, [slots.trigger?.(), slots.default?.()])
    }
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'size', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h(
          'select',
          {
            class: 'n-select',
            value: props.value,
            disabled: props.disabled,
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
  NTabPane: {
    name: 'NTabPane',
    props: ['name', 'tab'],
    setup(props: any, { slots }: any) {
      return () =>
        h(
          'div',
          { class: 'n-tab-pane', 'data-name': props.name, 'data-tab': props.tab },
          slots.default?.()
        )
    }
  },
  NTabs: {
    name: 'NTabs',
    props: ['value', 'type', 'animated'],
    emits: ['update:value'],
    setup(props: any, { slots }: any) {
      return () =>
        h(
          'div',
          {
            class: 'n-tabs',
            'data-value': props.value,
            'data-type': props.type,
            'data-animated': props.animated ? 'true' : 'false'
          },
          slots.default?.()
        )
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
  getAdminWorkerProfiles: mockGetAdminWorkerProfiles,
  getWorkerSharedConfiguration: mockGetWorkerSharedConfiguration,
  getAdminSkills: mockGetAdminSkills,
  testWorkerDockerConnection: mockTestWorkerDockerConnection,
  updateConfig: mockUpdateConfig,
  updateWorkerProfile: mockUpdateWorkerProfile,
  updateWorkerSharedConfiguration: mockUpdateWorkerSharedConfiguration,
  verifyWorkerProfileRuntime: mockVerifyWorkerProfileRuntime,
  createWorkerProfile: mockCreateWorkerProfile,
  deleteWorkerProfile: mockDeleteWorkerProfile,
  duplicateWorkerProfile: mockDuplicateWorkerProfile,
  enableWorkerProfile: mockEnableWorkerProfile,
  setDefaultWorkerProfile: mockSetDefaultWorkerProfile,
  disableWorkerProfile: mockDisableWorkerProfile
}))

describe('WorkerSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
    mockGetAdminWorkerProfiles.mockResolvedValue([createWorkerProfile()])
    mockGetWorkerSharedConfiguration.mockResolvedValue(createSharedConfiguration())
    mockGetAdminSkills.mockResolvedValue([])
    mockTestWorkerDockerConnection.mockResolvedValue({
      docker_host: 'tcp://arm-worker:2376',
      server_version: '27.1.0',
      architecture: 'aarch64',
      operating_system: 'Linux',
      elapsed_ms: 18
    })
    mockGetBuiltIns.mockResolvedValue({
      execute: { content: 'Execute {{user_prompt}}', available_placeholders: ['user_prompt'] },
      plan: { content: 'Plan {{user_prompt}}', available_placeholders: ['user_prompt'] },
      ci_auto_repair: { content: 'Repair {{issue_title}}', available_placeholders: ['issue_title'] }
    })
    mockUpdateConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
    mockUpdateWorkerProfile.mockResolvedValue(createWorkerProfile())
    mockUpdateWorkerSharedConfiguration.mockResolvedValue(
      createSharedConfiguration({ revision: 4, updated_at: '2026-08-15T01:00:00Z' })
    )
    mockVerifyWorkerProfileRuntime.mockResolvedValue({
      ok: true,
      runtime_readiness: { status: 'ready', checked_at: '2026-08-15T01:00:00Z', ready_until: null }
    })
    mockCreateWorkerProfile.mockResolvedValue(createWorkerProfile({ id: 2, name: 'Worker Profile 2' }))
    mockDeleteWorkerProfile.mockResolvedValue(undefined)
    mockDuplicateWorkerProfile.mockResolvedValue(createWorkerProfile({ id: 2, name: 'Default Worker Copy' }))
    mockEnableWorkerProfile.mockResolvedValue(createWorkerProfile({ enabled: true }))
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
    expect(mockGetAdminWorkerProfiles).toHaveBeenCalled()
    expect(wrapper.text()).toContain('Default Worker')
    expect((wrapper.vm as any).workerFormValue.image).toBe('codify-worker/java21-maven:2026.07')
    expect(wrapper.text()).not.toContain('config.aiProvider')
    expect(wrapper.text()).not.toContain('config.providers.movedNotice')
  })

  it('opens and saves the shared configuration as a separate revisioned editor', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()

    expect(wrapper.find('[data-testid="worker-profile-editor"]').exists()).toBe(true)
    await wrapper.find('[data-testid="worker-shared-configuration-entry"]').trigger('click')
    expect(wrapper.find('[data-testid="worker-shared-configuration-editor"]').exists()).toBe(true)

    const vm = wrapper.vm as any
    vm.sharedFormValue.pre_script = 'npm ci'
    vm.sharedFormValue.mounts = [
      { host_path: '/srv/cache', container_path: '/cache', mode: 'rw' }
    ]
    await vm.handleSaveSharedConfiguration()

    expect(mockUpdateWorkerSharedConfiguration).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_revision: 3,
        pre_script: 'npm ci',
        volume_mounts: [
          { host_path: '/srv/cache', container_path: '/cache', mode: 'rw' }
        ]
      })
    )
    expect(mockGetAdminWorkerProfiles).toHaveBeenCalledTimes(2)
    expect(mockMessage.success).toHaveBeenCalledWith('config.sharedConfigurationSaved')
  })

  it('composes system collection rows and serializes per-item masks without leaking secrets', async () => {
    mockGetWorkerSharedConfiguration.mockResolvedValueOnce(
      createSharedConfiguration({
        volume_mounts: [
          { host_path: '/srv/cache', container_path: '/cache', mode: 'ro' }
        ],
        environment_variables: [
          {
            id: 41,
            key: 'SHARED_TOKEN',
            value: null,
            is_secret: true,
            value_configured: true
          }
        ]
      })
    )
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        worker_kit_source: 'system',
        volume_mounts: [],
        volume_mount_masks: [],
        environment_variables: [],
        overrides: {
          worker_kit: null,
          pre_script: null,
          post_script: null,
          volume_mounts: [],
          masked_volume_mount_paths: [],
          environment_variables: []
        }
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.workerFormValue.mounts[0]).toEqual(
      expect.objectContaining({ container_path: '/cache', source: 'system' })
    )
    expect(vm.workerFormValue.environment_variables[0]).toEqual(
      expect.objectContaining({
        key: 'SHARED_TOKEN',
        value: '',
        value_configured: true,
        source: 'system'
      })
    )
    expect(wrapper.text()).not.toContain('shared-secret-value')

    vm.maskMount(0)
    vm.maskEnvironmentVariable(0)
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        volume_mounts: [],
        volume_mount_masks: ['/cache'],
        environment_variables: [
          {
            id: undefined,
            key: 'SHARED_TOKEN',
            value: null,
            is_secret: false,
            operation: 'mask'
          }
        ]
      })
    )
  })

  it('keeps overlapping shared and profile environment variable ids on distinct rows', async () => {
    mockGetWorkerSharedConfiguration.mockResolvedValueOnce(
      createSharedConfiguration({
        environment_variables: [
          {
            id: 7,
            key: 'SHARED_FLAG',
            value: 'shared',
            is_secret: false,
            value_configured: true
          }
        ]
      })
    )
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        worker_kit_source: 'system',
        environment_variables: [],
        overrides: {
          worker_kit: null,
          pre_script: null,
          post_script: null,
          volume_mounts: [],
          masked_volume_mount_paths: [],
          environment_variables: [
            {
              id: 7,
              key: 'PROFILE_ONLY',
              value: 'profile',
              is_secret: false,
              value_configured: true,
              operation: 'set'
            }
          ]
        }
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any
    const renderedKeys = wrapper
      .findAll('.config-compact-row--environment')
      .map((row) => (row.element as any).__vnode?.key)

    expect(renderedKeys).toEqual(['profile_new-7', 'system-7'])
    expect(new Set(renderedKeys).size).toBe(renderedKeys.length)

    const findRow = (key: string) =>
      wrapper.findAll('.config-compact-row--environment').find(
        (row) => (row.find('input').element as HTMLInputElement).value === key
      )!

    await findRow('SHARED_FLAG')
      .findAll('button')
      .find((button) => button.text() === 'config.overrideHere')!
      .trigger('click')
    await flushPromises()
    expect(vm.workerFormValue.environment_variables).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'SHARED_FLAG', source: 'profile_override' }),
        expect.objectContaining({ key: 'PROFILE_ONLY', source: 'profile_new' })
      ])
    )

    await findRow('SHARED_FLAG')
      .findAll('button')
      .find((button) => button.text() === 'config.restoreSystemValue')!
      .trigger('click')
    await flushPromises()
    expect(vm.workerFormValue.environment_variables).toEqual(
      expect.arrayContaining([
        expect.objectContaining({ key: 'SHARED_FLAG', source: 'system' }),
        expect.objectContaining({ key: 'PROFILE_ONLY', source: 'profile_new' })
      ])
    )

    await findRow('PROFILE_ONLY')
      .findAll('button')
      .find((button) => button.text() === 'config.remove')!
      .trigger('click')
    await flushPromises()
    expect(vm.workerFormValue.environment_variables).toEqual([
      expect.objectContaining({ key: 'SHARED_FLAG', source: 'system' })
    ])
  })

  it('keeps Kit and scripts inheritance distinct from explicit profile values', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        worker_kit_source: 'system',
        pre_script: null,
        post_script: null,
        default_execute_run_instruction_template: null,
        default_plan_run_instruction_template: null,
        ci_auto_repair_run_instruction_template: null
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.workerFormValue.worker_kit_source).toBe('system')
    expect(vm.workerFormValue.worker_pre_script).toBe(null)
    vm.setWorkerKitFollowsSystem(false)
    expect(vm.workerFormValue.worker_kit_source).toBe('profile')
    expect(vm.workerFormValue.worker_kit_version).toBe('0.4.0')

    vm.setScriptFollowsSystem('pre', false)
    expect(vm.workerFormValue.worker_pre_script).toBe('echo shared pre')
    vm.workerFormValue.worker_pre_script = ''
    await vm.handleSaveWorker()
    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({ pre_script: '' })
    )

    vm.setScriptFollowsSystem('pre', true)
    expect(vm.workerFormValue.worker_pre_script).toBe(null)
  })

  it('shows unavailable readiness details and re-verifies the selected profile', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValue([
      createWorkerProfile({
        worker_kit_source: 'system',
        runtime_readiness: {
          status: 'unavailable',
          checked_at: '2026-08-15T00:30:00Z',
          ready_until: null
        }
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()

    const status = wrapper.find('[data-testid="worker-profile-runtime-status"]')
    expect(status.text()).toContain('config.runtimeUnavailable')
    expect(status.text()).toContain('config.runtimeFailureDetailsUnavailable')

    await (wrapper.vm as any).handleVerifyProfileRuntime()
    expect(mockVerifyWorkerProfileRuntime).toHaveBeenCalledWith(1)
    expect(mockGetAdminWorkerProfiles).toHaveBeenCalledTimes(2)
    expect(mockMessage.success).toHaveBeenCalledWith('config.runtimeVerificationSucceeded')
  })

  it('reports a stale shared revision without claiming the save succeeded', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    mockUpdateWorkerSharedConfiguration.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'shared_configuration_changed' } }
    })

    ;(wrapper.vm as any).sharedFormValue.post_script = 'changed elsewhere'
    await (wrapper.vm as any).handleSaveSharedConfiguration()

    expect(mockMessage.error).toHaveBeenCalledWith('config.sharedConfigurationChanged')
    expect(mockMessage.success).not.toHaveBeenCalledWith('config.sharedConfigurationSaved')
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

  it('groups run instruction editors into mode tabs', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const tabs = wrapper.find('.config-run-instructions-tabs')
    expect(tabs.attributes('data-value')).toBe('execute')
    expect(tabs.attributes('data-type')).toBe('segment')
    expect(tabs.attributes('data-animated')).toBe('false')
    expect(tabs.findAll('.n-tab-pane').map((pane) => pane.attributes('data-name'))).toEqual([
      'execute',
      'plan',
      'ci_auto_repair'
    ])
    expect(tabs.findAll('.n-tab-pane').map((pane) => pane.attributes('data-tab'))).toEqual([
      'config.runInstructionImplementationTab',
      'config.runInstructionAnalysisTab',
      'config.runInstructionCiAutoRepairTab'
    ])
    expect(
      tabs.findAllComponents({ name: 'RunInstructionTemplateEditor' }).map((editor) =>
        editor.props('fixedRows')
      )
    ).toEqual([12, 12, 12])
  })

  it('applies prompt-only to manual modes and hides it for CI auto-repair', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const panes = wrapper.findAll('.config-run-instructions-tabs .n-tab-pane')
    const promptOnlyLabel = 'runInstruction.usePromptOnly'
    const executePromptOnly = panes[0]
      .findAll('.run-instruction-editor__actions button')
      .find((button) => button.text() === promptOnlyLabel)
    const planPromptOnly = panes[1]
      .findAll('.run-instruction-editor__actions button')
      .find((button) => button.text() === promptOnlyLabel)

    expect(executePromptOnly).toBeDefined()
    expect(planPromptOnly).toBeDefined()
    expect(panes[2].text()).not.toContain(promptOnlyLabel)

    await executePromptOnly!.trigger('click')
    await planPromptOnly!.trigger('click')

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.default_execute_run_instruction_template).toBe('{{user_prompt}}')
    expect(vm.workerFormValue.default_plan_run_instruction_template).toBe('{{user_prompt}}')
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
      mode: 'ro',
      source: 'profile_new'
    })
    expect(vm.workerFormValue.mounts[1].host_path).toBe('/host/cache')
    expect(vm.workerFormValue.environment_variables[0]).toEqual({
      key: '',
      value: '',
      is_secret: false,
      value_configured: false,
      source: 'profile_new'
    })
    expect(vm.workerFormValue.environment_variables[1].key).toBe('JAVA_OPTS')
  })

  it('sorts volume mounts by container path when loading and saving', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        volume_mounts: [
          { host_path: '/host/workspace', container_path: '/workspace', mode: 'rw' },
          { host_path: '/host/cache', container_path: '/cache', mode: 'rw' },
          { host_path: '/host/tools', container_path: '/opt/tools', mode: 'ro' }
        ]
      })
    ])

    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.mounts.map((mount: any) => mount.container_path)).toEqual([
      '/cache',
      '/opt/tools',
      '/workspace'
    ])

    vm.workerFormValue.mounts[2].container_path = '/bin'

    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        volume_mounts: [
          { host_path: '/host/workspace', container_path: '/bin', mode: 'rw' },
          { host_path: '/host/cache', container_path: '/cache', mode: 'rw' },
          { host_path: '/host/tools', container_path: '/opt/tools', mode: 'ro' }
        ]
      })
    )
  })

  it('keeps a newly added mount at the top after editing and blurring', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    vm.addMount()
    await flushPromises()

    const mountRows = wrapper.findAll('.config-compact-row--mount')
    const newContainerPathInput = mountRows[0].findAll('input')[1]
    await newContainerPathInput.setValue('/zzz/new')
    await newContainerPathInput.trigger('blur')

    expect(vm.workerFormValue.mounts.map((mount: any) => mount.container_path)).toEqual([
      '/zzz/new',
      '/container/cache'
    ])
  })

  it('keeps a newly added environment variable at the top after editing and blurring', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    vm.addEnvironmentVariable()
    await flushPromises()

    const environmentRows = wrapper.findAll('.config-compact-row--environment')
    const newKeyInput = environmentRows[0].find('input')
    await newKeyInput.setValue('ZZZ_NEW')
    await newKeyInput.trigger('blur')

    expect(vm.workerFormValue.environment_variables.map((item: any) => item.key)).toEqual([
      'ZZZ_NEW',
      'JAVA_OPTS',
      'SECRET_TOKEN'
    ])
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
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
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

  it('loads and saves mounted worker kit runtime settings', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        runtime_mode: 'mounted_kit',
        worker_kit_version: '0.1.0',
        worker_kit_path: '/opt/codify/worker-kits/0.1.0-linux-amd64'
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.runtime_mode).toBe('mounted_kit')
    expect(vm.workerFormValue.worker_kit_version).toBe('0.1.0')
    expect(vm.workerFormValue.worker_kit_path).toBe(
      '/opt/codify/worker-kits/0.1.0-linux-amd64'
    )
    expect(wrapper.text()).toContain('config.workerKitPath')

    vm.workerFormValue.worker_kit_version = '0.2.0'
    vm.workerFormValue.worker_kit_path = '/opt/codify/worker-kits/0.2.0-linux-amd64'
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        runtime_mode: 'mounted_kit',
        worker_kit_version: '0.2.0',
        worker_kit_path: '/opt/codify/worker-kits/0.2.0-linux-amd64'
      })
    )
  })

  it('loads and saves the enabled/default harness fields', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        enabled_harnesses: ['claude'],
        default_harness_key: 'claude',
        harness_constraints: {}
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    expect(vm.workerFormValue.enabled_harnesses).toEqual(['claude'])
    expect(vm.workerFormValue.default_harness_key).toBe('claude')

    vm.workerFormValue.enabled_harnesses = ['claude', 'codex']
    vm.workerFormValue.default_harness_key = 'codex'
    vm.workerFormValue.harness_constraints = { sandbox_mode: 'container-boundary' }
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        enabled_harnesses: ['claude', 'codex'],
        default_harness_key: 'codex',
        harness_constraints: { sandbox_mode: 'container-boundary' }
      })
    )
  })

  it('clears worker kit coordinates when saving baked image mode', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        runtime_mode: 'mounted_kit',
        worker_kit_version: '0.1.0',
        worker_kit_path: '/opt/codify/worker-kits/0.1.0-linux-amd64'
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: {
        isMobile: false,
        reloadKey: 0
      }
    })

    await flushPromises()

    const vm = wrapper.vm as any
    vm.workerFormValue.runtime_mode = 'baked_image'
    vm.workerFormValue.default_skill_ids = [11]
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        runtime_mode: 'baked_image',
        worker_kit_version: null,
        worker_kit_path: null,
        default_skill_ids: []
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
    await vm.handleSaveWorkspace()

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_workspace_retention_days: 30
      }
    })
  })

  it('loads, validates, and saves global task artifact settings', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.artifactFormValue).toEqual({
      maxTotalMiB: 200,
      maxFileMiB: 100,
      maxEntries: 5000,
      retentionDays: 30
    })
    expect(wrapper.text()).toContain('config.taskArtifacts')

    vm.artifactFormValue.maxTotalMiB = 256
    vm.artifactFormValue.maxFileMiB = 128
    vm.artifactFormValue.maxEntries = 6000
    vm.artifactFormValue.retentionDays = 60
    mockUpdateConfig.mockResolvedValueOnce({
      runtime: {
        ...createRuntimeConfig(),
        worker_artifacts_max_total_bytes: 256 * 1024 * 1024,
        worker_artifacts_max_file_bytes: 128 * 1024 * 1024,
        worker_artifacts_max_entries: 6000,
        worker_runtime_archive_retention_days: 60
      }
    })

    await vm.handleSaveArtifacts()

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_artifacts_max_total_bytes: 256 * 1024 * 1024,
        worker_artifacts_max_file_bytes: 128 * 1024 * 1024,
        worker_artifacts_max_entries: 6000,
        worker_runtime_archive_retention_days: 60
      }
    })
    expect(vm.isArtifactDirty).toBe(false)
  })

  it('does not save when the artifact file limit exceeds the total limit', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any
    vm.artifactFormValue.maxTotalMiB = 50
    vm.artifactFormValue.maxFileMiB = 51

    await vm.handleSaveArtifacts()

    expect(mockUpdateConfig).not.toHaveBeenCalled()
    expect(mockMessage.error).toHaveBeenCalledWith('config.artifactFileLimitError')
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
    expect(vm.workerFormValue.image).toBe('codify-worker/java21-maven:2026.07')
    expect(vm.workerFormValue.mounts).toEqual([])
    expect(vm.workerFormValue.environment_variables).toEqual([])
    expect(vm.workerFormValue.default_execute_run_instruction_template).toBe(null)
  })

  it('creates a profile with inherited (null) templates in a single create', async () => {
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
        worker_kit_source: 'system',
        volume_mounts: [],
        environment_variables: [],
        default_execute_run_instruction_template: null,
        default_plan_run_instruction_template: null,
        ci_auto_repair_run_instruction_template: null
      })
    )

    await vm.handleSaveWorker()

    // The create contract accepts NULL templates (= inherit the shared
    // baseline), so inherited templates are persisted in one atomic create
    // instead of a disabled-bootstrap + PATCH dance.
    expect(mockCreateWorkerProfile).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Java Worker',
        image: 'codify-worker-java:latest',
        enabled: true,
        codegraph_enabled: false,
        volume_mounts: [],
        environment_variables: [],
        default_execute_run_instruction_template: null,
        default_plan_run_instruction_template: null,
        ci_auto_repair_run_instruction_template: null,
        expected_shared_revision: 3
      })
    )
    expect(mockUpdateWorkerProfile).not.toHaveBeenCalled()
    expect(mockDeleteWorkerProfile).not.toHaveBeenCalled()
    expect(vm.selectedProfileId).toBe(3)
  })

  it('shows a shared-revision conflict when the single create is rejected', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.handleCreateProfile()
    vm.workerFormValue.name = 'Stale Worker'
    vm.workerFormValue.image = 'codify-worker:latest'
    mockCreateWorkerProfile.mockRejectedValueOnce({
      response: { status: 409, data: { detail: 'shared_configuration_changed' } }
    })

    await vm.handleSaveWorker()

    // A rejected single create leaves no bootstrap row to clean up and never
    // falls through to a PATCH.
    expect(mockCreateWorkerProfile).toHaveBeenCalledTimes(1)
    expect(mockUpdateWorkerProfile).not.toHaveBeenCalled()
    expect(mockDeleteWorkerProfile).not.toHaveBeenCalled()
    expect(mockMessage.error).toHaveBeenCalledWith('config.sharedConfigurationChanged')
    expect(vm.selectedProfileId).toBe(null)
  })

  it('enables a disabled worker profile from the profile actions', async () => {
    const disabledProfile = createWorkerProfile({
      id: 2,
      name: 'Disabled Worker',
      enabled: false,
      is_default: false
    })
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile(),
      disabledProfile
    ])
    mockEnableWorkerProfile.mockResolvedValueOnce({ ...disabledProfile, enabled: true })
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.selectProfile(2)
    await wrapper.vm.$nextTick()

    const enableButton = wrapper
      .findAll('button')
      .find((button) => button.text() === 'config.enableWorkerProfile')
    expect(enableButton).toBeDefined()
    await enableButton!.trigger('click')
    await flushPromises()

    expect(mockEnableWorkerProfile).toHaveBeenCalledWith(2)
    expect(vm.workerFormValue.enabled).toBe(true)
    expect(mockMessage.success).toHaveBeenCalledWith('config.workerProfileEnabled')
  })

  it('deletes a disabled unassigned worker profile and selects the default profile', async () => {
    const disabledProfile = createWorkerProfile({
      id: 2,
      name: 'Unused Worker',
      enabled: false,
      is_default: false
    })
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile(),
      disabledProfile
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()

    const vm = wrapper.vm as any
    vm.selectProfile(2)
    await vm.handleDeleteProfile()

    expect(mockDeleteWorkerProfile).toHaveBeenCalledWith(2)
    expect(vm.workerProfiles.map((profile: any) => profile.id)).toEqual([1])
    expect(vm.selectedProfileId).toBe(1)
    expect(vm.workerFormValue.name).toBe('Default Worker')
    expect(mockMessage.success).toHaveBeenCalledWith('config.workerProfileDeleted')
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
    expect(vm.isWorkspaceDirty).toBe(true)
    expect(mockMessage.error).toHaveBeenCalledWith('worker profile invalid')
  })

  it('sorts environment variables by name without exposing stored secret values', async () => {
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
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
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
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false,
            operation: 'set'
          },
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: '',
            is_secret: true,
            operation: 'set'
          }
        ]
      })
    )
    expect(vm.workerFormValue.environment_variables).toEqual([
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
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
    const configuredSecret = vm.workerFormValue.environment_variables.find(
      (environmentVariable: any) => environmentVariable.key === 'SECRET_TOKEN'
    )
    configuredSecret.value = 'new-secret-value'
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
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 19,
        key: 'NEW_SECRET',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 19,
        key: 'NEW_SECRET',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true,
        source: 'profile_new',
        system_value: undefined
      }
    ])
    expect(wrapper.text()).toContain('config.configured')
    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        environment_variables: [
          {
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false,
            operation: 'set'
          },
          {
            id: undefined,
            key: 'NEW_SECRET',
            value: 'brand-new-secret',
            is_secret: true,
            operation: 'set'
          },
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: 'new-secret-value',
            is_secret: true,
            operation: 'set'
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

  it('loads and tests a custom Docker daemon target', async () => {
    mockGetAdminWorkerProfiles.mockResolvedValueOnce([
      createWorkerProfile({
        docker_host: 'tcp://arm-worker:2376',
        docker_tls_ca: '/certs/ca.pem',
        docker_tls_cert: '/certs/cert.pem',
        docker_tls_key: '/certs/key.pem'
      })
    ])
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any

    expect(vm.workerFormValue.use_system_docker).toBe(false)
    await vm.handleTestDockerConnection()

    expect(mockTestWorkerDockerConnection).toHaveBeenCalledWith({
      docker_host: 'tcp://arm-worker:2376',
      docker_tls_ca: '/certs/ca.pem',
      docker_tls_cert: '/certs/cert.pem',
      docker_tls_key: '/certs/key.pem'
    })
    expect(vm.dockerTestResult.architecture).toBe('aarch64')
  })

  it('saves system Docker inheritance as null target fields', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const vm = wrapper.vm as any
    await vm.handleSaveWorker()

    expect(mockUpdateWorkerProfile).toHaveBeenCalledWith(
      1,
      expect.objectContaining({
        docker_host: null,
        docker_tls_ca: null,
        docker_tls_cert: null,
        docker_tls_key: null
      })
    )
    expect(mockUpdateConfig).not.toHaveBeenCalled()

    vm.workerFormValue.worker_workspace_retention_days = 21
    await vm.handleSaveWorkspace()

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_workspace_retention_days: 21
      }
    })
  })

  it('shows the deployment workspace path as read-only', async () => {
    const wrapper = mount(WorkerSettingsPanel, {
      props: { isMobile: false, reloadKey: 0 }
    })
    await flushPromises()
    const pathInput = wrapper.find('input[placeholder="/opt/codify-workspaces"]')
    expect(pathInput.attributes('disabled')).toBeDefined()
    expect(wrapper.text()).toContain('config.workerWorkspaceHostPathDeploymentHint')
  })
})
