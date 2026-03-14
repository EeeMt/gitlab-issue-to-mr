import { createRouter, createWebHistory } from 'vue-router'
import { authState, initializeAuth } from '../auth'
import Dashboard from '../views/Dashboard.vue'
import TaskView from '../views/TaskView.vue'
import Monitor from '../views/Monitor.vue'
import ScheduleOverview from '../views/ScheduleOverview.vue'
import Config from '../views/Config.vue'
import AccessManagement from '../views/AccessManagement.vue'
import OidcDiagnostics from '../views/OidcDiagnostics.vue'
import Sessions from '../views/Sessions.vue'
import CreateTask from '../views/CreateTask.vue'
import Login from '../views/Login.vue'

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
      component: Login,
      meta: { requiresAuth: false }
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: Dashboard,
      meta: { requiresAuth: true }
    },
    {
      path: '/create-task',
      name: 'CreateTask',
      component: CreateTask,
      meta: { requiresAuth: true }
    },
    {
      path: '/tasks/:id',
      name: 'TaskView',
      component: TaskView,
      meta: { requiresAuth: true }
    },
    {
      path: '/sessions',
      name: 'Sessions',
      component: Sessions,
      meta: { requiresAuth: true }
    },
    {
      path: '/monitor',
      name: 'Monitor',
      component: Monitor,
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/schedule-overview',
      name: 'ScheduleOverview',
      component: ScheduleOverview,
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/config',
      name: 'Config',
      component: Config,
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/access-management',
      name: 'AccessManagement',
      component: AccessManagement,
      meta: { requiresAuth: true, requiresAdmin: true }
    },
    {
      path: '/oidc-diagnostics',
      name: 'OidcDiagnostics',
      component: OidcDiagnostics,
      meta: { requiresAuth: true, requiresAdmin: true }
    }
  ]
})

router.beforeEach(async (to) => {
  await initializeAuth()

  if (!authState.oidcEnabled) {
    if (to.name === 'Login') {
      return { name: 'Dashboard' }
    }
    return true
  }

  const requiresAuth = to.meta.requiresAuth !== false
  const requiresAdmin = to.meta.requiresAdmin === true

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

  return true
})

export default router
