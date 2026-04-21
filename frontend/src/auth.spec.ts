import { describe, it, expect, vi, beforeEach, afterEach, type Mock } from 'vitest'
import { authState, initializeAuth, isAdmin, canAccessSharedPage, buildLoginUrl, startLogin, logoutAndClearAuth } from './auth'
import * as apiModule from './api'

vi.mock('./api')

const mockGetAuthStatus = apiModule.getAuthStatus as Mock

describe('auth module', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    // Reset authState to initial values
    authState.initialized = false
    authState.systemInitialized = false
    authState.loading = true
    authState.oidcEnabled = false
    authState.breakGlassEnabled = false
    authState.breakGlassUsername = null
    authState.authenticated = false
    authState.pagePermissions = {
      monitor: false,
      schedule_overview: false,
      analytics: false,
      oidc_diagnostics: false
    }
    authState.user = null
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  describe('initializeAuth', () => {
    it('should fetch auth status on first call', async () => {
      const mockStatus = {
        oidc_enabled: true,
        break_glass_enabled: false,
        break_glass_username: null,
        authenticated: true,
        page_permissions: {
          monitor: true,
          schedule_overview: false,
          analytics: false,
          oidc_diagnostics: false
        },
        user: {
          id: 1,
          gitlab_user_id: 100,
          username: 'testuser',
          display_name: 'Test User',
          email: 'test@example.com',
          avatar_url: null,
          platform_role: 'platform_user'
        },
        system_initialized: true
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      const result = await initializeAuth()

      expect(mockGetAuthStatus).toHaveBeenCalledTimes(1)
      expect(result).toEqual(mockStatus)
      expect(authState.oidcEnabled).toBe(true)
      expect(authState.authenticated).toBe(true)
      expect(authState.pagePermissions.monitor).toBe(true)
    })

    it('should return cached result on subsequent calls', async () => {
      const mockStatus = {
        oidc_enabled: true,
        break_glass_enabled: false,
        break_glass_username: null,
        authenticated: true,
        page_permissions: { monitor: true, schedule_overview: false, analytics: false, oidc_diagnostics: false },
        user: { id: 1, gitlab_user_id: 100, username: 'testuser', display_name: null, email: null, avatar_url: null, platform_role: 'platform_user' }
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      await initializeAuth()
      const result1 = await initializeAuth()
      const result2 = await initializeAuth()

      // Should only call API once due to caching
      expect(mockGetAuthStatus).toHaveBeenCalledTimes(1)
      expect(result1).toEqual(mockStatus)
      expect(result2).toEqual(mockStatus)
    })

    it('should fetch again when force=true', async () => {
      const mockStatus = {
        oidc_enabled: true,
        break_glass_enabled: false,
        break_glass_username: null,
        authenticated: true,
        page_permissions: { monitor: true, schedule_overview: false, analytics: false, oidc_diagnostics: false },
        user: { id: 1, gitlab_user_id: 100, username: 'testuser', display_name: null, email: null, avatar_url: null, platform_role: 'platform_user' }
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      await initializeAuth()
      await initializeAuth(true)

      // Should call API twice because of force=true
      expect(mockGetAuthStatus).toHaveBeenCalledTimes(2)
    })

    it('should handle fetch errors gracefully', async () => {
      mockGetAuthStatus.mockRejectedValue(new Error('Network error'))

      const result = await initializeAuth()

      // Should return fallback values on error
      expect(authState.initialized).toBe(true)
      expect(authState.oidcEnabled).toBe(true) // fallback
      expect(authState.authenticated).toBe(false) // fallback
      expect(result.oidc_enabled).toBe(true)
      expect(result.authenticated).toBe(false)
    })

    it('should set loading state correctly', async () => {
      expect(authState.loading).toBe(true)

      const mockStatus = {
        oidc_enabled: false,
        break_glass_enabled: false,
        break_glass_username: null,
        authenticated: false,
        page_permissions: { monitor: false, schedule_overview: false, analytics: false, oidc_diagnostics: false },
        user: null
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      const promise = initializeAuth()
      expect(authState.loading).toBe(true)

      await promise
      expect(authState.loading).toBe(false)
    })

    it('should handle missing optional fields in response', async () => {
      const mockStatus = {
        oidc_enabled: false,
        authenticated: false,
        page_permissions: null,
        user: null
        // Missing: break_glass_enabled, break_glass_username, system_initialized
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      await initializeAuth()

      expect(authState.breakGlassEnabled).toBe(false) // default fallback
      expect(authState.breakGlassUsername).toBe(null) // default fallback
      expect(authState.systemInitialized).toBe(false) // default fallback
    })
  })

  describe('authState', () => {
    it('should have correct initial state', () => {
      expect(authState.initialized).toBe(false)
      expect(authState.systemInitialized).toBe(false)
      expect(authState.loading).toBe(true)
      expect(authState.oidcEnabled).toBe(false)
      expect(authState.breakGlassEnabled).toBe(false)
      expect(authState.breakGlassUsername).toBe(null)
      expect(authState.authenticated).toBe(false)
      expect(authState.pagePermissions).toEqual({
        monitor: false,
        schedule_overview: false,
        analytics: false,
        oidc_diagnostics: false
      })
      expect(authState.user).toBe(null)
    })

    it('should be reactive and update correctly', async () => {
      const mockStatus = {
        oidc_enabled: true,
        break_glass_enabled: true,
        break_glass_username: 'admin',
        authenticated: true,
        page_permissions: {
          monitor: true,
          schedule_overview: true,
          analytics: true,
          oidc_diagnostics: true
        },
        user: {
          id: 2,
          gitlab_user_id: 200,
          username: 'admin',
          display_name: 'Admin User',
          email: 'admin@example.com',
          avatar_url: null,
          platform_role: 'platform_admin'
        }
      }
      mockGetAuthStatus.mockResolvedValue(mockStatus)

      await initializeAuth()

      expect(authState.oidcEnabled).toBe(true)
      expect(authState.breakGlassEnabled).toBe(true)
      expect(authState.breakGlassUsername).toBe('admin')
      expect(authState.authenticated).toBe(true)
      expect(authState.pagePermissions.analytics).toBe(true)
      expect(authState.user?.username).toBe('admin')
    })
  })

  describe('isAdmin', () => {
    it('should return true for platform_admin role', () => {
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'admin',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_admin'
      }

      expect(isAdmin.value).toBe(true)
    })

    it('should return false for platform_user role', () => {
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'user',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_user'
      }

      expect(isAdmin.value).toBe(false)
    })

    it('should return false when user is null', () => {
      authState.user = null

      expect(isAdmin.value).toBe(false)
    })

    it('should return false for other roles', () => {
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'operator',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'operator'
      }

      expect(isAdmin.value).toBe(false)
    })
  })

  describe('canAccessSharedPage', () => {
    beforeEach(() => {
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'testuser',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_user'
      }
    })

    it('should allow access when OIDC disabled', () => {
      authState.oidcEnabled = false

      expect(canAccessSharedPage('monitor')).toBe(true)
      expect(canAccessSharedPage('schedule_overview')).toBe(true)
      expect(canAccessSharedPage('analytics')).toBe(true)
      expect(canAccessSharedPage('oidc_diagnostics')).toBe(true)
    })

    it('should allow access for admins regardless of page permissions', () => {
      authState.oidcEnabled = true
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'admin',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_admin'
      }
      authState.pagePermissions = {
        monitor: false,
        schedule_overview: false,
        analytics: false,
        oidc_diagnostics: false
      }

      expect(canAccessSharedPage('monitor')).toBe(true)
      expect(canAccessSharedPage('analytics')).toBe(true)
    })

    it('should check page permissions for regular users when OIDC enabled', () => {
      authState.oidcEnabled = true
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'testuser',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_user'
      }
      authState.pagePermissions = {
        monitor: true,
        schedule_overview: false,
        analytics: false,
        oidc_diagnostics: false
      }

      expect(canAccessSharedPage('monitor')).toBe(true)
      expect(canAccessSharedPage('schedule_overview')).toBe(false)
      expect(canAccessSharedPage('analytics')).toBe(false)
    })

    it('should allow access for admins even when page permissions are false', () => {
      authState.oidcEnabled = true
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'admin',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_admin'
      }
      authState.pagePermissions = {
        monitor: false,
        schedule_overview: false,
        analytics: false,
        oidc_diagnostics: false
      }

      expect(canAccessSharedPage('monitor')).toBe(true)
      expect(canAccessSharedPage('schedule_overview')).toBe(true)
      expect(canAccessSharedPage('analytics')).toBe(true)
      expect(canAccessSharedPage('oidc_diagnostics')).toBe(true)
    })
  })

  describe('buildLoginUrl', () => {
    it('should build login URL with next parameter', () => {
      const url = buildLoginUrl('/dashboard')
      expect(url).toBe('/api/auth/login?next=%2Fdashboard')
    })

    it('should use current path when no next provided', () => {
      const originalLocation = window.location
      Object.defineProperty(window, 'location', {
        value: { pathname: '/tasks', search: '?status=pending' },
        writable: true
      })

      const url = buildLoginUrl()

      expect(url).toContain('/api/auth/login?next=')
      expect(url).toContain('%2Ftasks')

      Object.defineProperty(window, 'location', { value: originalLocation, writable: true })
    })
  })

  describe('startLogin', () => {
    it('should navigate to login URL', () => {
      const assignMock = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { assign: assignMock },
        writable: true
      })

      startLogin('/dashboard')

      expect(assignMock).toHaveBeenCalledWith('/api/auth/login?next=%2Fdashboard')
    })
  })

  describe('logoutAndClearAuth', () => {
    it('should call logout API and redirect to login', async () => {
      const mockLogout = vi.fn().mockResolvedValue(undefined)
      ;(apiModule as any).logout = mockLogout

      const assignMock = vi.fn()
      Object.defineProperty(window, 'location', {
        value: { assign: assignMock },
        writable: true
      })

      // Set some state
      authState.authenticated = true
      authState.user = {
        id: 1,
        gitlab_user_id: 100,
        username: 'testuser',
        display_name: null,
        email: null,
        avatar_url: null,
        platform_role: 'platform_user'
      }

      await logoutAndClearAuth()

      expect(authState.authenticated).toBe(false)
      expect(authState.user).toBe(null)
      expect(assignMock).toHaveBeenCalledWith('/login')
    })
  })
})
