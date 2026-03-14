import { computed, reactive } from 'vue'
import { getAuthStatus, logout as apiLogout, type AuthStatus, type AuthUser } from './api'

interface AuthState {
  initialized: boolean
  loading: boolean
  oidcEnabled: boolean
  authenticated: boolean
  user: AuthUser | null
}

export const authState = reactive<AuthState>({
  initialized: false,
  loading: false,
  oidcEnabled: false,
  authenticated: false,
  user: null
})

let inFlight: Promise<AuthStatus> | null = null

export async function initializeAuth(force = false): Promise<AuthStatus> {
  if (authState.initialized && !force) {
    return {
      oidc_enabled: authState.oidcEnabled,
      authenticated: authState.authenticated,
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
      authState.authenticated = status.authenticated
      authState.user = status.user
      authState.initialized = true
      return status
    })
    .catch(() => {
      const fallback = {
        oidc_enabled: true,
        authenticated: false,
        user: null
      }
      authState.oidcEnabled = fallback.oidc_enabled
      authState.authenticated = fallback.authenticated
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
  authState.user = null
  authState.initialized = true
  window.location.assign('/login')
}

export const isAdmin = computed(() => authState.user?.platform_role === 'platform_admin')
