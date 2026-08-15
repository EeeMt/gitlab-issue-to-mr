import { describe, expect, it } from 'vitest'
import router, { isDynamicImportFailure } from './index'

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

  describe('isDynamicImportFailure', () => {
    it('detects a stale hashed chunk after a deploy', () => {
      const error = new TypeError(
        'Failed to fetch dynamically imported module: http://192.168.50.129:8880/assets/ScheduleOverview-CDVDzA2U.js',
      )

      expect(isDynamicImportFailure(error)).toBe(true)
    })

    it('ignores unrelated navigation failures', () => {
      expect(isDynamicImportFailure(new Error('API request failed'))).toBe(false)
    })
  })
})
