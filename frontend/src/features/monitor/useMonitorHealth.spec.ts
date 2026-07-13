import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import type { Container, DockerTargetError, Stats, Task } from '../../api'
import { createMockContainer, createMockTask } from '../../test/mocks/api'
import { useMonitorHealth } from './useMonitorHealth'

const translate = (key: string) => key
const stats: Stats = {
  total: 3,
  pending: 1,
  queued: 1,
  running: 1,
  completed: 0,
  failed: 0,
  cancelled: 0,
  completed_24h: 2,
  failed_cancelled_24h: 0,
  running_long_30min: 0,
}

function createHealth(
  tasks: Task[],
  containers: Container[],
  dockerTargetErrors: DockerTargetError[] = [],
) {
  return useMonitorHealth({
    stats: ref(stats),
    tasks: ref(tasks),
    containers: ref(containers),
    dockerTargetErrors: ref(dockerTargetErrors),
    recentFinishedList: ref([]),
    recentFailureList: ref([]),
    nowMs: ref(new Date('2026-07-05T10:00:00Z').getTime()),
    translate,
  })
}

describe('useMonitorHealth', () => {
  it('keeps scheduler ordering and queue groups in one domain boundary', () => {
    const health = createHealth(
      [
        createMockTask({
          id: 1,
          status: 'queued',
          priority: 1,
          scheduled_at: '2026-07-05T11:00:00Z',
        }),
        createMockTask({ id: 2, status: 'running', priority: 2 }),
        createMockTask({ id: 3, status: 'pending', priority: 0 }),
      ],
      [],
    )

    expect(health.activeTasks.value.map((task) => task.id)).toEqual([2, 3, 1])
    expect(health.runningTasks.value.map((task) => task.id)).toEqual([2])
    expect(health.readyTasks.value.map((task) => task.id)).toEqual([3])
    expect(health.waitingTasks.value.map((task) => task.id)).toEqual([1])
  })

  it('derives container mismatches and health summary cards together', () => {
    const health = createHealth(
      [createMockTask({ id: 2, status: 'running', container_id: null })],
      [
        createMockContainer({ id: 'orphan', task_id: 99, status: 'running' }),
      ],
    )

    expect(health.runningTasksWithoutContainer.value).toHaveLength(1)
    expect(health.orphanContainers.value).toHaveLength(1)
    expect(
      health.overviewCards.value.find((card) => card.key === 'health')?.tagType,
    ).toBe('warning')
  })

  it('degrades overall health when a Docker target is unavailable', () => {
    const health = createHealth([], [], [{ docker_target: 'ARM Worker' }])

    expect(
      health.overviewCards.value.find((card) => card.key === 'health')?.tagType,
    ).toBe('warning')
    expect(
      health.overviewCards.value.find((card) => card.key === 'containers')?.tagType,
    ).toBe('warning')
    expect(health.healthChecks.value.find((check) => check.key === 'workers')?.type).toBe(
      'warning',
    )
  })
})
