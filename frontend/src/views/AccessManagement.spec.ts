import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import AccessManagement from './AccessManagement.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage, resetMockApi } = vi.hoisted(() => {
  const api = {
    getAdminUsers: vi.fn(),
    updateAdminUser: vi.fn(),
    revokeAdminUserSessions: vi.fn()
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }
  const resetMockApi = () => Object.values(api).forEach(fn => fn.mockReset())
  return { mockApi: api, mockMessage: msg, resetMockApi }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  getAdminUsers: mockApi.getAdminUsers,
  updateAdminUser: mockApi.updateAdminUser,
  revokeAdminUserSessions: mockApi.revokeAdminUserSessions
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeLocal: vi.fn((v: any) => `date:${v}`)
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string, params?: any) => {
      if (params) return `${key}:${JSON.stringify(params)}`
      return key
    }),
    locale: { value: 'en' }
  })
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
    isCompact: ref(false)
  })
}))

// ---------------------------------------------------------------------------
// Naive-UI mock
// ---------------------------------------------------------------------------
vi.mock('naive-ui', () => ({
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: props.show ? 'n-spin--loading' : 'n-spin' }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size', 'wrap'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-space' }, slots.default?.()) }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'secondary'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled || props.loading,
        onClick: () => emit('click')
      }, slots.default?.())
    }
  },
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, slots.default?.())
    }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NGrid: {
    name: 'NGrid',
    props: ['cols', 'xGap', 'yGap'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-grid' }, slots.default?.()) }
  },
  NGi: {
    name: 'NGi',
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-gi' }, slots.default?.()) }
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-tag' }, slots.default?.()) }
  },
  NAvatar: {
    name: 'NAvatar',
    props: ['round', 'src'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-avatar' }, slots.default?.()) }
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'clearable'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input',
        value: props.value,
        onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value)
      })
    }
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'loading', 'placeholder', 'clearable', 'disabled'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        onChange: (e: Event) => emit('update:value', (e.target as HTMLSelectElement).value || null)
      }, props.options?.map((o: any) => h('option', { value: o.value }, o.label)))
    }
  },
  NFormItem: {
    name: 'NFormItem',
    props: ['label'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-form-item' }, slots.default?.()) }
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description'],
    setup(props: any) { return () => h('div', { class: 'n-empty' }, props.description) }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const makeUser = (overrides: Record<string, any> = {}) => ({
  id: 1,
  username: 'alice',
  display_name: 'Alice Smith',
  email: 'alice@example.com',
  avatar_url: null,
  platform_role: 'platform_user',
  platform_role_source: 'manual',
  state: 'active',
  is_current_user: false,
  active_session_count: 2,
  gitlab_user_id: 10,
  last_login_at: '2026-01-01T00:00:00Z',
  last_session_seen_at: '2026-01-02T00:00:00Z',
  created_at: '2025-01-01T00:00:00Z',
  ...overrides
})

const mockUsers = [
  makeUser({ id: 1, username: 'alice', display_name: 'Alice Smith', email: 'alice@example.com', platform_role: 'platform_user', state: 'active', active_session_count: 2 }),
  makeUser({ id: 2, username: 'bob', display_name: 'Bob Jones', email: 'bob@example.com', platform_role: 'platform_admin', state: 'active', active_session_count: 1 }),
  makeUser({ id: 3, username: 'carol', display_name: 'Carol White', email: 'carol@example.com', platform_role: 'platform_user', state: 'disabled', active_session_count: 0, is_current_user: true })
]

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountComponent = () =>
  mount(AccessManagement, {
    global: {
      stubs: {
        PageHeader: {
          template: '<div class="page-header"><slot name="actions"/></div>'
        },
        SummaryCard: {
          props: ['label', 'value'],
          template: '<div class="summary-card"><span class="sc-label">{{ label }}</span><span class="sc-value">{{ value }}</span></div>'
        }
      }
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('AccessManagement', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    ;(mockApi.getAdminUsers as Mock).mockResolvedValue(mockUsers)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  // -------------------------------------------------------------------------
  it('calls getAdminUsers on mount', async () => {
    wrapper = mountComponent()
    await flushPromises()
    expect(mockApi.getAdminUsers).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('shows loading state during initial fetch', async () => {
    let resolve!: (v: any) => void
    ;(mockApi.getAdminUsers as Mock).mockReturnValue(new Promise(r => { resolve = r }))

    wrapper = mountComponent()
    await nextTick()

    expect(wrapper.vm.initialLoading).toBe(true)
    expect(wrapper.vm.usersLoading).toBe(true)

    resolve(mockUsers)
    await flushPromises()
    expect(wrapper.vm.usersLoading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('shows user cards after loading', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    const cards = wrapper.findAll('[data-testid="access-management-user-card"]')
    expect(cards.length).toBe(3)
  })

  // -------------------------------------------------------------------------
  it('shows empty state when no users match', async () => {
    ;(mockApi.getAdminUsers as Mock).mockResolvedValue([])
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.find('.n-empty').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('summary items computed correctly', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    const known = items.find((i: any) => i.label === 'accessManagement.knownUsers')
    const admins = items.find((i: any) => i.label === 'accessManagement.platformAdmins')
    const disabled = items.find((i: any) => i.label === 'accessManagement.disabledUsers')
    const sessions = items.find((i: any) => i.label === 'accessManagement.activeSessions')
    expect(known?.value).toBe('3')
    expect(admins?.value).toBe('1')
    expect(disabled?.value).toBe('1')
    expect(sessions?.value).toBe('3') // 2+1+0
  })

  // -------------------------------------------------------------------------
  it('filters users by search text', async () => {
    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.userSearch = 'alice'
    await nextTick()

    const filtered = wrapper.vm.filteredUsers as any[]
    expect(filtered.length).toBe(1)
    expect(filtered[0].username).toBe('alice')
  })

  // -------------------------------------------------------------------------
  it('filters users by role', async () => {
    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.roleFilter = 'platform_admin'
    await nextTick()

    const filtered = wrapper.vm.filteredUsers as any[]
    expect(filtered.length).toBe(1)
    expect(filtered[0].username).toBe('bob')
  })

  // -------------------------------------------------------------------------
  it('filters users by state', async () => {
    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.stateFilter = 'disabled'
    await nextTick()

    const filtered = wrapper.vm.filteredUsers as any[]
    expect(filtered.length).toBe(1)
    expect(filtered[0].username).toBe('carol')
  })

  // -------------------------------------------------------------------------
  it('save button calls updateAdminUser with changed fields', async () => {
    const updatedUser = makeUser({ id: 1, platform_role: 'platform_admin', state: 'active' })
    ;(mockApi.updateAdminUser as Mock).mockResolvedValue(updatedUser)

    wrapper = mountComponent()
    await flushPromises()

    // Modify alice's role draft
    wrapper.vm.userDrafts[1].platform_role = 'platform_admin'
    await nextTick()

    await wrapper.vm.handleSaveUser(mockUsers[0])
    await flushPromises()

    expect(mockApi.updateAdminUser).toHaveBeenCalledWith(1, { platform_role: 'platform_admin' })
    expect(mockMessage.success).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('revoke sessions button calls revokeAdminUserSessions', async () => {
    ;(mockApi.revokeAdminUserSessions as Mock).mockResolvedValue({ revoked_count: 2 })

    wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.handleRevokeUserSessions(mockUsers[0])
    await flushPromises()

    expect(mockApi.revokeAdminUserSessions).toHaveBeenCalledWith(1)
    expect(mockMessage.success).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('shows success message with count=0 when no active sessions to revoke', async () => {
    ;(mockApi.revokeAdminUserSessions as Mock).mockResolvedValue({ revoked_count: 0 })

    wrapper = mountComponent()
    await flushPromises()

    await wrapper.vm.handleRevokeUserSessions(mockUsers[0])
    await flushPromises()

    expect(mockMessage.success).toHaveBeenCalled()
  })

  // -------------------------------------------------------------------------
  it('handles getAdminUsers error gracefully', async () => {
    ;(mockApi.getAdminUsers as Mock).mockRejectedValue({ response: { data: { detail: 'Forbidden' } } })
    wrapper = mountComponent()
    await flushPromises()

    expect(mockMessage.error).toHaveBeenCalled()
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.vm.usersLoading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('isUserDirty returns true when draft differs from user', async () => {
    wrapper = mountComponent()
    await flushPromises()

    wrapper.vm.userDrafts[1].platform_role = 'platform_admin'
    await nextTick()

    expect(wrapper.vm.isUserDirty(mockUsers[0])).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('isUserDirty returns false when draft matches user', async () => {
    wrapper = mountComponent()
    await flushPromises()

    // alice.platform_role = 'platform_user' and draft should also be 'platform_user'
    expect(wrapper.vm.isUserDirty(mockUsers[0])).toBe(false)
  })
})
