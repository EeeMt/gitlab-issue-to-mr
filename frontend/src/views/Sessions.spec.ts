import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, type VueWrapper } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import Sessions from './Sessions.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage } = vi.hoisted(() => {
  const api = {
    getSessions: vi.fn(),
    revokeSession: vi.fn()
  }
  const msg = {
    error: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
    info: vi.fn()
  }
  return { mockApi: api, mockMessage: msg }
})

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('../api', () => ({
  getSessions: mockApi.getSessions,
  revokeSession: mockApi.revokeSession
}))

vi.mock('../auth', () => ({
  initializeAuth: vi.fn(),
  logoutAndClearAuth: vi.fn()
}))

vi.mock('../utils/datetime', () => ({
  formatDateTimeLocal: vi.fn((v: string) => `date:${v}`)
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' }
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: { value: 1200 } }))
}))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: { value: false },
    isCompact: { value: false }
  })
}))

// ---------------------------------------------------------------------------
// Naive-UI mock
// ---------------------------------------------------------------------------
vi.mock('naive-ui', () => ({
  NCard: {
    name: 'NCard',
    props: ['bordered', 'size'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-card' }, slots.default?.()) }
  },
  NButton: {
    name: 'NButton',
    props: ['type', 'loading', 'disabled', 'block', 'strong', 'quaternary', 'size', 'secondary'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.disabled || props.loading,
        onClick: () => emit('click')
      }, slots.default?.())
    }
  },
  NSpace: {
    name: 'NSpace',
    props: ['vertical', 'size'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-space' }, slots.default?.()) }
  },
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-alert' }, slots.default?.()) }
  },
  NIcon: {
    name: 'NIcon',
    props: ['size', 'component'],
    setup() { return () => h('span', { class: 'n-icon' }) }
  },
  NText: {
    name: 'NText',
    props: ['depth'],
    setup(_p: any, { slots }: any) { return () => h('span', slots.default?.()) }
  },
  NTag: {
    name: 'NTag',
    props: ['size', 'round', 'type'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-tag' }, slots.default?.()) }
  },
  NSpin: {
    name: 'NSpin',
    props: ['show', 'description'],
    setup(_p: any, { slots }: any) { return () => h('div', { class: 'n-spin' }, slots.default?.()) }
  },
  NEmpty: {
    name: 'NEmpty',
    props: ['description'],
    setup(props: any) { return () => h('div', { class: 'n-empty' }, props.description) }
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
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Mock session data
// ---------------------------------------------------------------------------
const mockSessions = [
  {
    id: 'session-id-1234567890ab',
    status: 'active',
    current: true,
    ip_address: '192.168.1.1',
    user_agent: 'Mozilla/5.0',
    created_at: '2026-01-01T00:00:00Z',
    last_seen_at: '2026-01-02T00:00:00Z',
    expires_at: '2026-02-01T00:00:00Z',
    has_gitlab_access_token: true,
    has_gitlab_refresh_token: true
  },
  {
    id: 'session-id-revoked-0001',
    status: 'revoked',
    current: false,
    ip_address: null,
    user_agent: null,
    created_at: '2026-01-01T00:00:00Z',
    last_seen_at: '2026-01-01T00:00:00Z',
    expires_at: null,
    has_gitlab_access_token: false,
    has_gitlab_refresh_token: false
  }
]

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountSessions = () =>
  mount(Sessions, {
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

describe('Sessions', () => {
  let wrapper: VueWrapper<any>

  beforeEach(() => {
    vi.clearAllMocks()
  })

  afterEach(() => {
    if (wrapper) wrapper.unmount()
  })

  // -------------------------------------------------------------------------
  it('calls getSessions on mount', async () => {
    mockApi.getSessions.mockResolvedValue([])
    wrapper = mountSessions()
    await vi.waitFor(() => expect(mockApi.getSessions).toHaveBeenCalledTimes(1))
  })

  // -------------------------------------------------------------------------
  it('shows loading state before first fetch completes', async () => {
    let resolvePromise: (v: any) => void
    const pending = new Promise(r => { resolvePromise = r })
    mockApi.getSessions.mockReturnValue(pending)

    wrapper = mountSessions()
    await nextTick()

    // hasLoadedOnce is still false → initialLoading = true
    expect(wrapper.vm.initialLoading).toBe(true)
    expect(wrapper.vm.loading).toBe(true)
    expect(wrapper.vm.hasLoadedOnce).toBe(false)

    resolvePromise!([])
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))
  })

  // -------------------------------------------------------------------------
  it('shows sessions after loading', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))

    // Two session cards should be rendered
    const cards = wrapper.findAll('.n-card')
    expect(cards.length).toBeGreaterThanOrEqual(2)
  })

  // -------------------------------------------------------------------------
  it('shows empty state when no sessions', async () => {
    mockApi.getSessions.mockResolvedValue([])
    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))

    expect(wrapper.find('.n-empty').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('summary shows correct counts', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))

    const items = wrapper.vm.summaryItems
    // knownSessions = 2, activeSessions = 1, refreshCapable = 1
    const known = items.find((i: any) => i.label === 'sessions.knownSessions')
    const active = items.find((i: any) => i.label === 'sessions.activeSessions')
    const refresh = items.find((i: any) => i.label === 'sessions.refreshCapable')
    expect(known?.value).toBe('2')
    expect(active?.value).toBe('1')
    expect(refresh?.value).toBe('1')
  })

  // -------------------------------------------------------------------------
  it('current session summary shows truncated id', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))

    const items = wrapper.vm.summaryItems
    const current = items.find((i: any) => i.label === 'sessions.currentSession')
    // shortId('session-id-1234567890ab') → 'session-…90ab'
    expect(current?.value).toBe('session-…90ab')
  })

  // -------------------------------------------------------------------------
  it('revoke button calls revokeSession with session id', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    mockApi.revokeSession.mockResolvedValue({ current_session_revoked: false })
    // After revoke, fetchSessions is called again
    mockApi.getSessions.mockResolvedValueOnce(mockSessions).mockResolvedValue([mockSessions[0]])

    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))
    await nextTick()

    // Find the revoke button for the active session (first card)
    const revokeButtons = wrapper.findAll('button')
    const activeRevoke = revokeButtons.find(b => b.text().includes('common.revoke') && !b.attributes('disabled'))
    expect(activeRevoke).toBeTruthy()
    await activeRevoke!.trigger('click')

    await vi.waitFor(() => {
      expect(mockApi.revokeSession).toHaveBeenCalledWith('session-id-1234567890ab')
    })
  })

  // -------------------------------------------------------------------------
  it('revoke button disabled for non-active sessions', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))
    await nextTick()

    // The revoked session's button should be disabled
    const revokeButtons = wrapper.findAll('button').filter(b => b.text().includes('common.revoke'))
    // Second button belongs to the revoked session
    expect(revokeButtons.length).toBeGreaterThanOrEqual(2)
    expect(revokeButtons[1].attributes('disabled')).toBeDefined()
  })

  // -------------------------------------------------------------------------
  it('calls logoutAndClearAuth when current session is revoked', async () => {
    mockApi.getSessions.mockResolvedValue(mockSessions)
    mockApi.revokeSession.mockResolvedValue({ current_session_revoked: true })

    const { logoutAndClearAuth } = await import('../auth')

    wrapper = mountSessions()
    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))
    await nextTick()

    const revokeButtons = wrapper.findAll('button')
    const activeRevoke = revokeButtons.find(b => b.text().includes('common.revoke') && !b.attributes('disabled'))
    await activeRevoke!.trigger('click')

    await vi.waitFor(() => {
      expect(logoutAndClearAuth).toHaveBeenCalled()
    })
  })

  // -------------------------------------------------------------------------
  it('handles fetch error gracefully', async () => {
    mockApi.getSessions.mockRejectedValue({ response: { data: { detail: 'Unauthorized' } } })
    wrapper = mountSessions()

    await vi.waitFor(() => expect(wrapper.vm.hasLoadedOnce).toBe(true))

    expect(mockMessage.error).toHaveBeenCalled()
    // Still marks as loaded
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.vm.loading).toBe(false)
  })
})
