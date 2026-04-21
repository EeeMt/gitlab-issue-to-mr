import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { h, nextTick, ref } from 'vue'
import OidcDiagnostics from './OidcDiagnostics.vue'

// ---------------------------------------------------------------------------
// Hoisted mocks
// ---------------------------------------------------------------------------
const { mockApi, mockMessage, resetMockApi } = vi.hoisted(() => {
  const api = {
    getOidcDiagnostics: vi.fn()
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
  getOidcDiagnostics: mockApi.getOidcDiagnostics
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
    locale: { value: 'en' }
  })
}))

vi.mock('@vueuse/core', () => ({
  useWindowSize: vi.fn(() => ({ width: ref(1200) }))
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
    props: ['loading', 'disabled'],
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
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    }
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
  NAlert: {
    name: 'NAlert',
    props: ['type', 'showIcon'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-alert' }, slots.default?.())
    }
  },
  useMessage: () => mockMessage
}))

// ---------------------------------------------------------------------------
// Mock data
// ---------------------------------------------------------------------------
const mockDiagnostics = {
  oidc_enabled: true,
  break_glass_enabled: false,
  client_id_configured: true,
  client_secret_configured: true,
  cookie_secure: true,
  cookie_samesite: 'lax',
  session_ttl_seconds: 3600,
  issuer_url: 'https://auth.example.com',
  discovery_issuer: 'https://auth.example.com',
  redirect_uri: 'https://app.example.com/auth/callback',
  authorization_endpoint: 'https://auth.example.com/authorize',
  token_endpoint: 'https://auth.example.com/token',
  userinfo_endpoint: 'https://auth.example.com/userinfo',
  required_scopes: ['openid', 'profile', 'email'],
  required_scope_string: 'openid profile email',
  authorization_url_preview: 'https://auth.example.com/authorize?client_id=abc',
  warnings: [],
  checks: [
    { key: 'client_id', label: 'Client ID configured', status: 'ok', detail: 'Client ID is set' },
    { key: 'client_secret', label: 'Client Secret configured', status: 'ok', detail: 'Secret is set' },
    { key: 'discovery', label: 'OIDC Discovery', status: 'warning', detail: 'Discovery endpoint slow' },
    { key: 'redirect', label: 'Redirect URI', status: 'error', detail: 'Redirect URI mismatch' }
  ]
}

// ---------------------------------------------------------------------------
// Mount helper
// ---------------------------------------------------------------------------
const mountComponent = () =>
  mount(OidcDiagnostics, {
    global: {
      stubs: {}
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('OidcDiagnostics', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  beforeEach(() => {
    resetMockApi()
    ;(mockApi.getOidcDiagnostics as Mock).mockResolvedValue(mockDiagnostics)
  })

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  // -------------------------------------------------------------------------
  it('calls getOidcDiagnostics on mount', async () => {
    wrapper = mountComponent()
    await flushPromises()
    expect(mockApi.getOidcDiagnostics).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('shows loading state during initial fetch', async () => {
    let resolve!: (v: any) => void
    ;(mockApi.getOidcDiagnostics as Mock).mockReturnValue(new Promise(r => { resolve = r }))

    wrapper = mountComponent()
    await nextTick()

    expect(wrapper.vm.initialLoading).toBe(true)
    expect(wrapper.vm.loading).toBe(true)

    resolve(mockDiagnostics)
    await flushPromises()

    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.initialLoading).toBe(false)
  })

  // -------------------------------------------------------------------------
  it('stores diagnostics data after successful fetch', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.diagnostics).not.toBeNull()
    expect(wrapper.vm.diagnostics.oidc_enabled).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('summary items are computed correctly from diagnostics', async () => {
    wrapper = mountComponent()
    await flushPromises()

    const items = wrapper.vm.summaryItems as any[]
    expect(items.length).toBe(4)

    const oidcStatus = items.find((i: any) => i.label === 'oidcDiagnostics.oidcLoginSummary')
    const healthy = items.find((i: any) => i.label === 'oidcDiagnostics.healthyChecks')
    const warnings = items.find((i: any) => i.label === 'oidcDiagnostics.warnings')
    const errors = items.find((i: any) => i.label === 'oidcDiagnostics.errors')

    // oidc_enabled = true → 'common.enabled'
    expect(oidcStatus?.value).toBe('common.enabled')
    // 2 ok, 1 warning, 1 error
    expect(healthy?.value).toBe('2')
    expect(warnings?.value).toBe('1')
    expect(errors?.value).toBe('1')
  })

  // -------------------------------------------------------------------------
  it('refresh button calls getOidcDiagnostics again', async () => {
    wrapper = mountComponent()
    await flushPromises()

    ;(mockApi.getOidcDiagnostics as Mock).mockClear()

    const btn = wrapper.find('button.n-button')
    await btn.trigger('click')
    await flushPromises()

    expect(mockApi.getOidcDiagnostics).toHaveBeenCalledTimes(1)
  })

  // -------------------------------------------------------------------------
  it('handles fetch error gracefully', async () => {
    ;(mockApi.getOidcDiagnostics as Mock).mockRejectedValue({
      response: { data: { detail: 'Unauthorized' } }
    })

    wrapper = mountComponent()
    await flushPromises()

    expect(mockMessage.error).toHaveBeenCalled()
    expect(wrapper.vm.hasLoadedOnce).toBe(true)
    expect(wrapper.vm.loading).toBe(false)
    expect(wrapper.vm.diagnostics).toBeNull()
  })

  // -------------------------------------------------------------------------
  it('tagType returns correct NaiveUI type for each check status', async () => {
    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.vm.tagType('ok')).toBe('success')
    expect(wrapper.vm.tagType('warning')).toBe('warning')
    expect(wrapper.vm.tagType('error')).toBe('error')
    expect(wrapper.vm.tagType('unknown')).toBe('default')
  })

  // -------------------------------------------------------------------------
  it('shows warnings alert when diagnostics has warnings', async () => {
    const diagWithWarnings = {
      ...mockDiagnostics,
      warnings: ['Warning 1', 'Warning 2']
    }
    ;(mockApi.getOidcDiagnostics as Mock).mockResolvedValue(diagWithWarnings)

    wrapper = mountComponent()
    await flushPromises()

    expect(wrapper.find('.n-alert').exists()).toBe(true)
  })

  // -------------------------------------------------------------------------
  it('summaryItems returns empty array before data loads', async () => {
    let resolve!: (v: any) => void
    ;(mockApi.getOidcDiagnostics as Mock).mockReturnValue(new Promise(r => { resolve = r }))

    wrapper = mountComponent()
    await nextTick()

    expect(wrapper.vm.summaryItems).toEqual([])

    resolve(mockDiagnostics)
    await flushPromises()

    expect(wrapper.vm.summaryItems.length).toBe(4)
  })
})
