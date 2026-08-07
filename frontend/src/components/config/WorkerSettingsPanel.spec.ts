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
    created_at: '2026-06-25T00:00:00',
    updated_at: '2026-06-25T00:00:00',
    ...overrides
  }
}

const {
  mockGetConfig,
  mockGetBuiltIns,
  mockGetAdminWorkerProfiles,
  mockGetAdminSkills,
  mockTestWorkerDockerConnection,
  mockUpdateConfig,
  mockUpdateWorkerProfile,
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
  mockGetAdminSkills: vi.fn(),
  mockTestWorkerDockerConnection: vi.fn(),
  mockUpdateConfig: vi.fn(),
  mockUpdateWorkerProfile: vi.fn(),
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
  getAdminSkills: mockGetAdminSkills,
  testWorkerDockerConnection: mockTestWorkerDockerConnection,
  updateConfig: mockUpdateConfig,
  updateWorkerProfile: mockUpdateWorkerProfile,
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
      mode: 'ro'
    })
    expect(vm.workerFormValue.mounts[1].host_path).toBe('/host/cache')
    expect(vm.workerFormValue.environment_variables[0]).toEqual({
      key: '',
      value: '',
      is_secret: false,
      value_configured: false
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
        value_configured: true
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
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
            id: 8,
            key: 'JAVA_OPTS',
            value: '-Xmx512m',
            is_secret: false
          },
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: '',
            is_secret: true
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
        value_configured: true
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
        value_configured: true
      },
      {
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
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
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
      }
    ])
    expect(vm.lastLoadedWorker.environment_variables).toEqual([
      {
        id: 8,
        key: 'JAVA_OPTS',
        value: '-Xmx512m',
        is_secret: false,
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
        id: 7,
        key: 'SECRET_TOKEN',
        value: '',
        is_secret: true,
        value_configured: true
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
            is_secret: false
          },
          {
            id: undefined,
            key: 'NEW_SECRET',
            value: 'brand-new-secret',
            is_secret: true
          },
          {
            id: 7,
            key: 'SECRET_TOKEN',
            value: 'new-secret-value',
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
