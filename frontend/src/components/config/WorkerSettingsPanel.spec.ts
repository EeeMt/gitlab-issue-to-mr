import { describe, expect, it, vi, beforeEach } from 'vitest'
import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import WorkerSettingsPanel from './WorkerSettingsPanel.vue'

function createRuntimeConfig() {
  return {
    worker_volume_mounts:
      '[{"host_path":"/host/cache","container_path":"/container/cache","mode":"rw"}]',
    maven_cache_host_path: '/data/.m2/repository',
    maven_settings_host_path: '/data/.m2/settings.xml',
    worker_environment_variables: [
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
    worker_pre_script: 'echo pre',
    worker_post_script: 'echo post'
  }
}

const { mockGetConfig, mockUpdateConfig, mockMessage } = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockUpdateConfig: vi.fn(),
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
  NInput: {
    name: 'NInput',
    props: ['value', 'type', 'placeholder', 'showPasswordOn'],
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
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options'],
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
  NTag: {
    name: 'NTag',
    props: ['type', 'round'],
    setup(props: any, { slots }: any) {
      return () => h('span', { class: ['n-tag', `n-tag--${props.type || 'default'}`] }, slots.default?.())
    }
  },
  useMessage: () => mockMessage
}))

vi.mock('../../api', () => ({
  getConfig: mockGetConfig,
  updateConfig: mockUpdateConfig
}))

describe('WorkerSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
    mockUpdateConfig.mockResolvedValue({
      runtime: createRuntimeConfig()
    })
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
    expect(wrapper.text()).not.toContain('config.aiProvider')
    expect(wrapper.text()).not.toContain('config.providers.movedNotice')
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

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: expect.objectContaining({
        worker_pre_script: 'npm ci',
        worker_post_script: 'npm test'
      })
    })
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

    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_volume_mounts: '[{"host_path":"/host/cache","container_path":"/container/cache","mode":"rw"}]',
        worker_pre_script: 'echo pre',
        worker_post_script: 'echo post',
        maven_cache_host_path: '/data/.m2/repository',
        maven_settings_host_path: '/data/.m2/settings.xml',
        worker_environment_variables: [
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
      }
    })
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

    mockUpdateConfig.mockResolvedValueOnce({
      runtime: {
        worker_volume_mounts:
          '[{"host_path":"/host/cache","container_path":"/container/cache","mode":"rw"}]',
        worker_pre_script: 'echo pre',
        worker_post_script: 'echo post',
        maven_cache_host_path: '/data/.m2/repository',
        maven_settings_host_path: '/data/.m2/settings.xml',
        worker_environment_variables: [
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
      }
    })

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
    expect(mockUpdateConfig).toHaveBeenCalledWith({
      runtime: {
        worker_volume_mounts: '[{"host_path":"/host/cache","container_path":"/container/cache","mode":"rw"}]',
        worker_pre_script: 'echo pre',
        worker_post_script: 'echo post',
        maven_cache_host_path: '/data/.m2/repository',
        maven_settings_host_path: '/data/.m2/settings.xml',
        worker_environment_variables: [
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
      }
    })
  })
})
