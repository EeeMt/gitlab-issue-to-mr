import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import UsageManagement from './UsageManagement.vue'

const { mockApi, mockMessage, resetMockApi } = vi.hoisted(() => {
  const api = {
    getAdminUsageLimitDefault: vi.fn(),
    updateAdminUsageLimitDefault: vi.fn(),
    listAdminUsageLimitUsers: vi.fn(),
    updateAdminUsageLimitUser: vi.fn(),
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn(),
  }
  const reset = () => Object.values(api).forEach((fn) => fn.mockReset())
  return { mockApi: api, mockMessage: msg, resetMockApi: reset }
})

vi.mock('../api', () => ({
  getAdminUsageLimitDefault: mockApi.getAdminUsageLimitDefault,
  updateAdminUsageLimitDefault: mockApi.updateAdminUsageLimitDefault,
  listAdminUsageLimitUsers: mockApi.listAdminUsageLimitUsers,
  updateAdminUsageLimitUser: mockApi.updateAdminUsageLimitUser,
}))

vi.mock('../utils/usageLimits', () => ({
  formatUsageResetAt: vi.fn((value: string) => `formatted:${value}`),
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string, params?: Record<string, unknown>) =>
      params ? `${key}:${JSON.stringify(params)}` : key
    ),
  }),
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
    isCompact: ref(false),
  }),
}))

vi.mock('naive-ui', () => ({
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-alert' }, slots.default?.())
    },
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () =>
        h(
          'button',
          {
            class: 'n-button',
            disabled: props.disabled || props.loading,
            onClick: () => emit('click'),
          },
          slots.default?.()
        )
    },
  },
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.(), slots.action?.()])
    },
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-form-item' }, slots.default?.())
    },
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
  },
  NGi: {
    name: 'NGi',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input',
          value: props.value,
          onInput: (event: Event) => emit('update:value', (event.target as HTMLInputElement).value),
        })
    },
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'min', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input-number',
          type: 'number',
          disabled: props.disabled,
          value: props.value ?? '',
          onInput: (event: Event) => emit('update:value', Number((event.target as HTMLInputElement).value)),
        })
    },
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h(
          'select',
          {
            class: 'n-select',
            disabled: props.disabled,
            value: props.value,
            onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value),
          },
          props.options?.map((option: any) => h('option', { value: option.value }, option.label))
        )
    },
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'wrap', 'justify'],
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin--loading' : 'n-spin' }, slots.default?.())
    },
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'size', 'round'],
    setup(_props: any, { slots }: any) {
      return () => h('span', { class: 'n-tag' }, slots.default?.())
    },
  },
  useMessage: () => mockMessage,
}))

const makePolicyValue = (mode: 'inherit' | 'custom' | 'unlimited', value: number | null) => ({
  mode,
  value,
})

const defaultPolicy = {
  daily_tokens: makePolicyValue('custom', 1000),
  weekly_tokens: makePolicyValue('custom', 4000),
  daily_tasks: makePolicyValue('custom', 5),
  weekly_tasks: makePolicyValue('unlimited', null),
}

const makeUserRow = (overrides: Partial<Record<string, any>> = {}) => ({
  user_id: 7,
  username: 'alice',
  display_name: 'Alice Smith',
  usage: {
    daily_tokens: 120,
    weekly_tokens: 800,
    daily_tasks: 2,
    weekly_tasks: 4,
  },
  limits: defaultPolicy,
  overrides: {
    daily_tokens: makePolicyValue('inherit', null),
    weekly_tokens: makePolicyValue('custom', 5000),
    daily_tasks: makePolicyValue('inherit', null),
    weekly_tasks: makePolicyValue('unlimited', null),
  },
  reset_at: {
    daily: '2026-04-29T00:00:00+08:00',
    weekly: '2026-05-04T00:00:00+08:00',
  },
  ...overrides,
})

const mountComponent = () =>
  mount(UsageManagement, {
    global: {
      stubs: {
        PageHeader: {
          props: ['title', 'subtitle'],
          template: '<div class="page-header">{{ title }}{{ subtitle }}<slot name="actions" /></div>',
        },
        SummaryCard: {
          props: ['label', 'value'],
          template: '<div class="summary-card"><span>{{ label }}</span><span>{{ value }}</span></div>',
        },
      },
    },
  })

describe('UsageManagement', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    Object.values(mockMessage).forEach((fn) => fn.mockReset())
    ;(mockApi.getAdminUsageLimitDefault as Mock).mockResolvedValue(defaultPolicy)
    ;(mockApi.listAdminUsageLimitUsers as Mock).mockResolvedValue([makeUserRow()])
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  it('loads usage defaults and users on mount', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(mockApi.getAdminUsageLimitDefault).toHaveBeenCalledTimes(1)
    expect(mockApi.listAdminUsageLimitUsers).toHaveBeenCalledTimes(1)
  })

  it('renders fetched user usage details', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.find('[data-testid="usage-management-page"]').exists()).toBe(true)
    expect(wrapper.text()).toContain('alice')
    expect(wrapper.text()).toContain('120')
    expect(wrapper.text()).toContain('formatted:2026-04-29T00:00:00+08:00')
  })

  it('saves the system default limits', async () => {
    ;(mockApi.updateAdminUsageLimitDefault as Mock).mockResolvedValue({
      ...defaultPolicy,
      daily_tokens: makePolicyValue('custom', 2000),
    })

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.defaultDraft.daily_tokens = makePolicyValue('custom', 2000)
    await nextTick()

    await wrapper.vm.handleSaveDefault()
    await flushPromises()

    expect(mockApi.updateAdminUsageLimitDefault).toHaveBeenCalledWith(
      expect.objectContaining({
        daily_tokens: { mode: 'custom', value: 2000 },
      })
    )
    expect(mockMessage.success).toHaveBeenCalled()
  })

  it('clears stale default values when switching a limit to unlimited', async () => {
    ;(mockApi.updateAdminUsageLimitDefault as Mock).mockResolvedValue({
      ...defaultPolicy,
      daily_tokens: makePolicyValue('unlimited', null),
    })

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.updateDefaultMode('daily_tokens', 'unlimited')
    await nextTick()

    await wrapper.vm.handleSaveDefault()
    await flushPromises()

    expect(mockApi.updateAdminUsageLimitDefault).toHaveBeenCalledWith(
      expect.objectContaining({
        daily_tokens: { mode: 'unlimited', value: null },
      })
    )
  })

  it('saves a user override', async () => {
    ;(mockApi.updateAdminUsageLimitUser as Mock).mockResolvedValue(
      makeUserRow({
        overrides: {
          daily_tokens: makePolicyValue('custom', 2500),
          weekly_tokens: makePolicyValue('custom', 5000),
          daily_tasks: makePolicyValue('inherit', null),
          weekly_tasks: makePolicyValue('unlimited', null),
        },
      })
    )

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.userDrafts[7].daily_tokens = makePolicyValue('custom', 2500)
    await nextTick()

    await wrapper.vm.handleSaveUser(makeUserRow())
    await flushPromises()

    expect(mockApi.updateAdminUsageLimitUser).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        daily_tokens: { mode: 'custom', value: 2500 },
      })
    )
    expect(mockMessage.success).toHaveBeenCalled()
  })

  it('initializes missing user custom values before saving overrides', async () => {
    ;(mockApi.updateAdminUsageLimitUser as Mock).mockResolvedValue(
      makeUserRow({
        overrides: {
          daily_tokens: makePolicyValue('custom', 1),
          weekly_tokens: makePolicyValue('custom', 5000),
          daily_tasks: makePolicyValue('inherit', null),
          weekly_tasks: makePolicyValue('unlimited', null),
        },
      })
    )

    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.updateUserMode(7, 'daily_tokens', 'custom')
    await nextTick()

    await wrapper.vm.handleSaveUser(makeUserRow())
    await flushPromises()

    expect(mockApi.updateAdminUsageLimitUser).toHaveBeenCalledWith(
      7,
      expect.objectContaining({
        daily_tokens: { mode: 'custom', value: 1 },
      })
    )
  })
})
