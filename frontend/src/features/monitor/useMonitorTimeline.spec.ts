import { computed, effectScope, ref } from 'vue'
import { describe, expect, it } from 'vitest'
import { createMockTask } from '../../test/mocks/api'
import { useMonitorTimeline } from './useMonitorTimeline'

describe('useMonitorTimeline', () => {
  it('builds a padded timeline range and clamps task positions', () => {
    const scope = effectScope()
    const timeline = scope.run(() => {
      const tasks = ref([
        createMockTask({
          status: 'running',
          started_at: '2026-07-05T08:00:00Z',
        }),
      ])
      return useMonitorTimeline({
        activeTasks: computed(() => tasks.value),
        nowMs: ref(new Date('2026-07-05T10:00:00Z').getTime()),
      })
    })!

    expect(timeline.timelineRange.value.start).toBeLessThan(
      new Date('2026-07-05T08:00:00Z').getTime(),
    )
    expect(timeline.timelinePct(Number.NEGATIVE_INFINITY)).toBe(0)
    expect(timeline.timelinePct(Number.POSITIVE_INFINITY)).toBe(100)
    expect(timeline.timelineTicks.value.length).toBeGreaterThan(0)
    scope.stop()
  })
})
