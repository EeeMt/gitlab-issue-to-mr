import { computed, type Ref } from 'vue'
import type { Container, Stats, Task } from '../../api'
import { parseUtcDate } from '../../utils/datetime'

export interface MonitorRuntimeOptions {
  stats: Ref<Stats>
  containers: Ref<Container[]>
  tasks: Ref<Task[]>
  recentFinishedList: Ref<Task[]>
  recentFailureList: Ref<Task[]>
  nowMs: Ref<number>
  translate: (key: string, params?: Record<string, unknown>) => string
}

const ACTIVE_STATUSES = ['pending', 'queued', 'running']

export function useMonitorRuntimeState(options: MonitorRuntimeOptions) {
  const tasksById = computed(
    () => new Map(options.tasks.value.map((task) => [task.id, task])),
  )
  const activeTasks = computed(() => {
    const now = options.nowMs.value
    return options.tasks.value
      .filter((task) => ACTIVE_STATUSES.includes(task.status))
      .sort((left, right) => {
        const leftRunning = left.status === 'running' ? 0 : 1
        const rightRunning = right.status === 'running' ? 0 : 1
        if (leftRunning !== rightRunning) return leftRunning - rightRunning

        const leftReady =
          !left.scheduled_at || parseUtcDate(left.scheduled_at).getTime() <= now ? 0 : 1
        const rightReady =
          !right.scheduled_at || parseUtcDate(right.scheduled_at).getTime() <= now
            ? 0
            : 1
        if (leftReady !== rightReady) return leftReady - rightReady

        if (leftReady === 0 && rightReady === 0) {
          if (left.priority !== right.priority) return left.priority - right.priority
          const leftDue = left.scheduled_at ? 0 : 1
          const rightDue = right.scheduled_at ? 0 : 1
          if (leftDue !== rightDue) return leftDue - rightDue
          if (left.scheduled_at && right.scheduled_at) {
            const difference =
              parseUtcDate(left.scheduled_at).getTime() -
              parseUtcDate(right.scheduled_at).getTime()
            if (difference !== 0) return difference
          }
          return (
            parseUtcDate(left.created_at).getTime() -
            parseUtcDate(right.created_at).getTime()
          )
        }

        if (left.scheduled_at && right.scheduled_at) {
          return (
            parseUtcDate(left.scheduled_at).getTime() -
            parseUtcDate(right.scheduled_at).getTime()
          )
        }
        return 0
      })
  })

  const runningTasks = computed(() =>
    activeTasks.value.filter((task) => task.status === 'running'),
  )
  const pendingQueuedTasks = computed(() =>
    activeTasks.value.filter(
      (task) => task.status === 'pending' || task.status === 'queued',
    ),
  )
  const readyTasks = computed(() => {
    const now = options.nowMs.value
    return pendingQueuedTasks.value.filter(
      (task) =>
        !task.scheduled_at || parseUtcDate(task.scheduled_at).getTime() <= now,
    )
  })
  const waitingTasks = computed(() => {
    const now = options.nowMs.value
    return pendingQueuedTasks.value.filter(
      (task) =>
        task.scheduled_at != null &&
        parseUtcDate(task.scheduled_at).getTime() > now,
    )
  })
  const runningContainers = computed(() =>
    options.containers.value.filter((container) => container.status === 'running'),
  )
  const linkedRunningContainers = computed(() =>
    runningContainers.value.filter((container) => {
      const task = container.task_id
        ? tasksById.value.get(container.task_id)
        : undefined
      return task?.status === 'running'
    }),
  )
  const runningTasksWithoutContainer = computed(() =>
    runningTasks.value.filter(
      (task) =>
        !runningContainers.value.some(
          (container) =>
            container.task_id === task.id || container.id === task.container_id,
        ),
    ),
  )
  const orphanContainers = computed(() =>
    runningContainers.value.filter((container) => {
      if (!container.task_id) return true
      const task = tasksById.value.get(container.task_id)
      return !task || task.status !== 'running'
    }),
  )
  const recentFinishedTasks = computed(() => options.recentFinishedList.value)
  const recentFailures = computed(() => options.recentFailureList.value)
  const recentFinishedCount24h = computed(
    () => options.stats.value.completed_24h,
  )
  const recentFailureCount24h = computed(
    () => options.stats.value.failed_cancelled_24h,
  )
  const longRunningTasks = computed(() =>
    runningTasks.value.filter(
      (task) =>
        !!task.started_at &&
        Date.now() - parseUtcDate(task.started_at).getTime() > 30 * 60 * 1000,
    ),
  )
  const sortedContainers = computed(() =>
    [...options.containers.value].sort((left, right) => {
      if (left.status === 'running' && right.status !== 'running') return -1
      if (left.status !== 'running' && right.status === 'running') return 1
      return parseTimestamp(right.created_at) - parseTimestamp(left.created_at)
    }),
  )
  const statusBreakdown = computed(() => {
    const total = Math.max(options.stats.value.total, 1)
    return ['pending', 'queued', 'running', 'completed', 'failed', 'cancelled'].map(
      (key) => {
        const value = options.stats.value[key as keyof Stats] as number
        return {
          key,
          label: options.translate(`monitor.${key}`),
          value,
          percent: (value / total) * 100,
        }
      },
    )
  })

  return {
    activeTasks,
    linkedRunningContainers,
    longRunningTasks,
    orphanContainers,
    pendingQueuedTasks,
    readyTasks,
    recentFailureCount24h,
    recentFailures,
    recentFinishedCount24h,
    recentFinishedTasks,
    runningContainers,
    runningTasks,
    runningTasksWithoutContainer,
    sortedContainers,
    statusBreakdown,
    tasksById,
    waitingTasks,
  }
}

function parseTimestamp(value?: string | null): number {
  if (!value) return 0
  const parsed = parseUtcDate(value).getTime()
  return Number.isNaN(parsed) ? 0 : parsed
}
