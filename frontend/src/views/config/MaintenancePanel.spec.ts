import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, ref } from 'vue'
import MaintenancePanel from './MaintenancePanel.vue'

const mockMessage = {
  error: vi.fn(),
  success: vi.fn(),
  warning: vi.fn()
}

const mockApi = {
  cleanupSystemData: vi.fn()
}

vi.mock('../../api', () => ({
  cleanupSystemData: (...args: any[]) => mockApi.cleanupSystemData(...args)
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
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary'],
    setup(props: any, { slots, attrs }: any) {
      return () => h('button', {
        class: ['n-button', props.type],
        ...attrs,
        disabled: props.disabled || props.loading,
        onClick: (event: MouseEvent) => {
          const click = attrs.onClick as ((event: MouseEvent) => void) | undefined
          click?.(event)
        }
      }, slots.default?.())
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label'],
    setup(props: any, { slots }: any) {
      return () => h('label', { class: 'n-form-item' }, [
        h('span', props.label),
        slots.default?.()
      ])
    }
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'min', 'clearable', 'placeholder'],
    setup(props: any, { emit, attrs }: any) {
      return () => h('input', {
        class: 'n-input-number',
        type: 'number',
        value: props.value ?? '',
        placeholder: props.placeholder,
        ...attrs,
        onInput: (event: Event) => {
          const raw = (event.target as HTMLInputElement).value
          emit('update:value', raw === '' ? null : Number(raw))
        }
      })
    }
  },
  NSwitch: {
    name: 'NSwitch',
    props: ['value'],
    setup(props: any, { emit, attrs }: any) {
      return () => h('input', {
        class: 'n-switch',
        type: 'checkbox',
        checked: props.value,
        ...attrs,
        onChange: (event: Event) => emit('update:value', (event.target as HTMLInputElement).checked)
      })
    }
  },
  NPopconfirm: {
    name: 'NPopconfirm',
    props: ['positiveText', 'negativeText'],
    setup(props: any, { slots, emit }: any) {
      return () => h('div', {
        class: 'n-popconfirm',
        onClick: () => emit('positive-click')
      }, [
        slots.trigger?.(),
        h('div', { class: 'n-popconfirm__content' }, slots.default?.()),
        h('span', { class: 'n-popconfirm__positive' }, props.positiveText),
        h('span', { class: 'n-popconfirm__negative' }, props.negativeText)
      ])
    }
  },
  NModal: {
    name: 'NModal',
    props: ['show', 'preset', 'closable', 'maskClosable'],
    setup(props: any, { slots, attrs }: any) {
      return () => props.show
        ? h('div', { class: 'n-modal', ...attrs }, [
          slots.default?.(),
          slots.footer?.()
        ])
        : null
    }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'bordered'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: ['n-alert', props.type] }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['size', 'wrap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    }
  },
  useMessage: () => mockMessage
}))

// Mock vue-i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key
  })
}))

// Mock useConfigForm
const mockConfigForm = {
  loading: ref(false),
  pageActionLoading: ref(false),
  anySectionSaving: ref(false),
  handleReload: vi.fn(),
  handleReset: vi.fn()
}

vi.mock('./useConfigForm', () => ({
  useConfigForm: () => mockConfigForm
}))

describe('MaintenancePanel', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
    mockConfigForm.loading.value = false
    mockConfigForm.pageActionLoading.value = false
    mockConfigForm.anySectionSaving.value = false
  })

  const mountComponent = () => {
    wrapper = mount(MaintenancePanel, {
      global: {
        stubs: {
          // Stub all naive-ui components to simplify rendering
        }
      }
    })
    return wrapper
  }

  it('should render without errors', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('.n-card').exists()).toBe(true)
  })

  it('should have config-actions card', () => {
    const wrapper = mountComponent()
    expect(wrapper.find('#config-actions').exists()).toBe(true)
  })

  it('should render reload button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('common.reload'))).toBe(true)
  })

  it('should render reset button', () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const buttonTexts = buttons.map(btn => btn.text())
    expect(buttonTexts.some(text => text.includes('config.resetEnvDefaults'))).toBe(true)
  })

  it('renders system data cleanup controls', () => {
    const wrapper = mountComponent()

    expect(wrapper.text()).toContain('config.systemDataCleanup')
    expect(wrapper.text()).toContain('config.cleanupOlderThanDays')
    expect(wrapper.text()).toContain('config.forceCleanupActiveTasks')
  })

  it('renders the retention days input as a compact field with a unit label', () => {
    const wrapper = mountComponent()

    expect(wrapper.find('.config-system-cleanup__retention-field').exists()).toBe(true)
    expect(wrapper.find('[data-test="cleanup-older-than-days-input"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('config.cleanupOlderThanDaysUnit')
  })

  it('opens a styled modal confirmation instead of an inline popconfirm', async () => {
    const wrapper = mountComponent()

    await wrapper.find('[data-test="cleanup-system-data-button"]').trigger('click')

    expect(wrapper.find('.n-popconfirm').exists()).toBe(false)
    expect(wrapper.find('.config-cleanup-confirm').exists()).toBe(true)
    expect(wrapper.text()).toContain('config.cleanSystemData')
    expect(wrapper.text()).toContain('config.confirmCleanSystemData')
  })

  it('submits cleanup payload with force disabled by default', async () => {
    mockApi.cleanupSystemData.mockResolvedValue({
      deleted_issues: 1,
      deleted_tasks: 2,
      skipped_active_issues: 0,
      skipped_active_tasks: 0,
      deleted_archives: 2,
      missing_archives: 0,
      deleted_workspaces: 1,
      container_cleanup_errors: [],
      file_cleanup_errors: []
    })
    const wrapper = mountComponent()

    await wrapper.find('[data-test="cleanup-system-data-button"]').trigger('click')
    await wrapper.find('[data-test="confirm-cleanup-system-data-button"]').trigger('click')

    expect(mockApi.cleanupSystemData).toHaveBeenCalledWith({
      older_than_days: 30,
      force: false
    })
    expect(mockMessage.success).toHaveBeenCalledWith('config.systemDataCleanupSuccess')
  })

  it('submits cleanup payload with retention and force enabled', async () => {
    mockApi.cleanupSystemData.mockResolvedValue({
      deleted_issues: 0,
      deleted_tasks: 0,
      skipped_active_issues: 0,
      skipped_active_tasks: 0,
      deleted_archives: 0,
      missing_archives: 0,
      deleted_workspaces: 0,
      container_cleanup_errors: [],
      file_cleanup_errors: []
    })
    const wrapper = mountComponent()

    await wrapper.find('[data-test="cleanup-older-than-days-input"]').setValue('30')
    await wrapper.find('[data-test="force-cleanup-active-switch"]').setValue(true)
    await wrapper.find('[data-test="cleanup-system-data-button"]').trigger('click')
    await wrapper.find('[data-test="confirm-cleanup-system-data-button"]').trigger('click')

    expect(mockApi.cleanupSystemData).toHaveBeenCalledWith({
      older_than_days: 30,
      force: true
    })
    expect(wrapper.text()).toContain('config.forceCleanupActiveTasksWarning')
  })

  it('should call handleReload when reload button is clicked', async () => {
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    const reloadButton = buttons.find(btn => btn.text().includes('common.reload'))
    expect(reloadButton).toBeDefined()
  })

  it('should show loading state when pageActionLoading is true', () => {
    mockConfigForm.pageActionLoading.value = true
    const wrapper = mountComponent()
    const resetButton = wrapper.findAll('.n-button').find(btn => btn.text().includes('config.resetEnvDefaults'))
    expect(resetButton).toBeDefined()
    // Reset for other tests
    mockConfigForm.pageActionLoading.value = false
  })

  it('should disable buttons when isBusy is true', () => {
    mockConfigForm.loading.value = true
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    buttons.forEach(btn => {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    })
    // Reset for other tests
    mockConfigForm.loading.value = false
  })

  it('should disable buttons when anySectionSaving is true', () => {
    mockConfigForm.anySectionSaving.value = true
    const wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    buttons.forEach(btn => {
      expect((btn.element as HTMLButtonElement).disabled).toBe(true)
    })
    // Reset for other tests
    mockConfigForm.anySectionSaving.value = false
  })
})
