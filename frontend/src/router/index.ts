import { createRouter, createWebHistory } from 'vue-router'
import Dashboard from '../views/Dashboard.vue'
import TaskView from '../views/TaskView.vue'
import Monitor from '../views/Monitor.vue'
import Config from '../views/Config.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/dashboard'
    },
    {
      path: '/dashboard',
      name: 'Dashboard',
      component: Dashboard
    },
    {
      path: '/tasks/:id',
      name: 'TaskView',
      component: TaskView
    },
    {
      path: '/monitor',
      name: 'Monitor',
      component: Monitor
    },
    {
      path: '/config',
      name: 'Config',
      component: Config
    }
  ]
})

export default router
