import { computed, reactive } from 'vue'
import { getAuthStatus, logout as apiLogout, type AuthStatus, type AuthUser, type PagePermissions } from './api'

const defaultPagePermissions = (): PagePermissions => ({
  monitor: false,
  schedule_overview: false,
  analytics: false,
  oidc_diagnostics: false
})

interface AuthState {
  initialized: boolean
  loading: boolean
  oidcEnabled: boolean
  breakGlassEnabled: boolean
  breakGlassUsername: string | null
  authenticated: boolean
  pagePermissions: PagePermissions
  user: AuthUser | null
}

export const authState = reactive<AuthState>({
  initialized: false,
  loading: true,
  oidcEnabled: false,
  breakGlassEnabled: false,
  breakGlassUsername: null,
  authenticated: false,
  pagePermissions: defaultPagePermissions(),
  user: null
})

let inFlight: Promise<AuthStatus> | null = null

export async function initializeAuth(force = false): Promise<AuthStatus> {
  if (authState.initialized && !force) {
      return {
        oidc_enabled: authState.oidcEnabled,
        break_glass_enabled: authState.breakGlassEnabled,
        break_glass_username: authState.breakGlassUsername,
        authenticated: authState.authenticated,
        page_permissions: authState.pagePermissions,
        user: authState.user
      }
  }

  if (inFlight && !force) {
    return inFlight
  }

  authState.loading = true
  inFlight = getAuthStatus()
    .then((status) => {
      authState.oidcEnabled = status.oidc_enabled
      authState.breakGlassEnabled = Boolean(status.break_glass_enabled)
      authState.breakGlassUsername = status.break_glass_username ?? null
      authState.authenticated = status.authenticated
      authState.pagePermissions = status.page_permissions ?? defaultPagePermissions()
      authState.user = status.user
      authState.initialized = true
      return status
    })
    .catch(() => {
      const fallback = {
        oidc_enabled: true,
        break_glass_enabled: false,
        break_glass_username: null,
        authenticated: false,
        page_permissions: defaultPagePermissions(),
        user: null
      }
      authState.oidcEnabled = fallback.oidc_enabled
      authState.breakGlassEnabled = fallback.break_glass_enabled
      authState.breakGlassUsername = fallback.break_glass_username
      authState.authenticated = fallback.authenticated
      authState.pagePermissions = fallback.page_permissions
      authState.user = fallback.user
      authState.initialized = true
      return fallback
    })
    .finally(() => {
      authState.loading = false
      inFlight = null
    })

  return inFlight
}

export function buildLoginUrl(next?: string): string {
  const target = next || `${window.location.pathname}${window.location.search}`
  return `/api/auth/login?next=${encodeURIComponent(target)}`
}

export function startLogin(next?: string) {
  window.location.assign(buildLoginUrl(next))
}

export async function logoutAndClearAuth() {
  await apiLogout()
  authState.authenticated = false
  authState.pagePermissions = defaultPagePermissions()
  authState.user = null
  authState.initialized = true
  window.location.assign('/login')
}

export const isAdmin = computed(() => authState.user?.platform_role === 'platform_admin')
export const canAccessSharedPage = (pageKey: keyof PagePermissions) =>
  !authState.oidcEnabled || isAdmin.value || authState.pagePermissions[pageKey]
