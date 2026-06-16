import { describe, expect, it } from 'vitest'
import router from './index'

describe('router', () => {
  it('lazy-loads view components to keep initial page loads responsive', () => {
    const routesWithViewComponents = router
      .getRoutes()
      .filter((route) => route.name && !route.redirect && route.components?.default)

    expect(routesWithViewComponents.map((route) => route.name)).toEqual(
      expect.arrayContaining([
        'Dashboard',
        'TaskList',
        'TaskView',
        'Monitor',
        'ScheduleOverview',
        'Analytics',
        'Config',
        'AccessManagement',
        'UsageManagement',
        'Sessions',
        'Login',
        'Bootstrap',
      ]),
    )

    for (const route of routesWithViewComponents) {
      expect(typeof route.components!.default).toBe('function')
    }
  })
})
