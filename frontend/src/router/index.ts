import { createRouter, createWebHistory } from 'vue-router'
import { authState, canAccessSharedPage, initializeAuth } from '../auth'
import type { PagePermissions } from '../api'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard'
    },
    {
      path: '/login',
      name: 'Login',
      component: () => import('../views/Login.vue'),
      meta: { requiresAuth: false }
    },
    {
      path: '/bootstrap',
      name: 'Bootstrap',
      component: () => import('../views/Bootstrap.vue'),
      meta: { requiresAuth: false, requiresBootstrap: true }
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: () => import('../views/Dashboard.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/create-task',
      redirect: '/issues/create',
    },
    {
      path: '/tasks',
      name: 'TaskList',
      component: () => import('../views/TaskList.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/issues',
      name: 'Issues',
      component: () => import('../views/IssueList.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/issues/create',
      name: 'CreateIssue',
      component: () => import('../views/CreateIssue.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/issues/:id',
      name: 'IssueView',
      component: () => import('../views/IssueView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/tasks/:id',
      name: 'TaskView',
      component: () => import('../views/TaskView.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/sessions',
      name: 'Sessions',
      component: () => import('../views/Sessions.vue'),
      meta: { requiresAuth: true }
    },
    {
      path: '/monitor',
      name: 'Monitor',
      component: () => import('../views/Monitor.vue'),
      meta: { requiresAuth: true, pagePermission: 'monitor' }
    },
    {
      path: '/schedule-overview',
      name: 'ScheduleOverview',
      component: () => import('../views/ScheduleOverview.vue'),
      meta: { requiresAuth: true, pagePermission: 'schedule_overview' }
    },
    {
      path: '/analytics',
      name: 'Analytics',
      component: () => import('../views/Analytics.vue'),
      meta: { requiresAuth: true, pagePermission: 'analytics' }
    },
    {
      path: '/configuration',
      name: 'Config',
      component: () => import('../views/Config.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/config',
      redirect: '/configuration'
    },
    {
      path: '/access-management',
      name: 'AccessManagement',
      component: () => import('../views/AccessManagement.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/usage-management',
      name: 'UsageManagement',
      component: () => import('../views/UsageManagement.vue'),
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/oidc-diagnostics',
      name: 'OidcDiagnostics',
      redirect: '/configuration?tab=auth'
    }
  ]
})

const CHUNK_RELOAD_KEY = 'codify:chunk-reload-at'
const CHUNK_RELOAD_COOLDOWN_MS = 30_000
let chunkReloadAttemptedInMemory = false

export function isDynamicImportFailure(error: unknown): boolean {
  if (!(error instanceof Error)) return false
  return (
    error.message.includes('Failed to fetch dynamically imported module') ||
    error.message.includes('Importing a module script failed') ||
    error.message.includes('Loading chunk') ||
    (error.name === 'TypeError' && /\/assets\/[^"']+\.(?:js|css)/.test(error.message))
  )
}

// After a deploy the old hashed lazy chunks disappear, so a page that is still
// open references a URL that no longer exists. Reload once to pick up the new
// index.html instead of leaving the router stuck in a failed navigation.
router.onError((error, to) => {
  if (!isDynamicImportFailure(error)) {
    console.error('Navigation failed:', error)
    return
  }

  let canReload = false
  try {
    const lastReloadAt = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) ?? 0)
    canReload = Date.now() - lastReloadAt >= CHUNK_RELOAD_COOLDOWN_MS
    if (canReload) {
      sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()))
    }
  } catch {
    canReload = !chunkReloadAttemptedInMemory
    chunkReloadAttemptedInMemory = true
  }

  if (!canReload) {
    console.error('Stale chunk load failed; skipping auto-reload within cooldown:', error)
    return
  }

  window.location.assign(to.fullPath.startsWith('/') ? to.fullPath : '/')
})

router.beforeEach(async (to) => {
  await initializeAuth()

  // Redirect to bootstrap page if system not initialized
  if (!authState.systemInitialized && authState.initialized !== undefined) {
    if (to.name !== 'Bootstrap') {
      return { name: 'Bootstrap' }
    }
    return true
  }

  // If system is initialized, prevent access to bootstrap page
  if (authState.systemInitialized && to.name === 'Bootstrap') {
    return { name: 'Dashboard' }
  }

  if (!authState.oidcEnabled) {
    if (to.name === 'Login') {
      if (authState.authenticated) {
        return { name: 'Dashboard' }
      }
      return true
    }
    // OIDC disabled - still require authentication for protected pages
    const requiresAuth = to.meta.requiresAuth !== false
    if (requiresAuth && !authState.authenticated) {
      return {
        name: 'Login',
        query: { next: to.fullPath }
      }
    }
    return true
  }

  const requiresAuth = to.meta.requiresAuth !== false
  const requiresAdmin = to.meta.requiresAdmin === true
  const pagePermission = to.meta.pagePermission as keyof PagePermissions | undefined

  if (to.name === 'Login') {
    if (authState.authenticated) {
      return { name: 'Dashboard' }
    }
    return true
  }

  if (requiresAuth && !authState.authenticated) {
    return {
      name: 'Login',
      query: { next: to.fullPath }
    }
  }

  if (requiresAdmin && authState.user?.platform_role !== 'platform_admin') {
    return { name: 'Dashboard' }
  }

  if (pagePermission && !canAccessSharedPage(pagePermission)) {
    return { name: 'Dashboard' }
  }

  return true
})

export default router
