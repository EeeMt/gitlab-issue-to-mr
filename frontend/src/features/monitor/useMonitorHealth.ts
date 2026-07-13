import { computed, type Ref } from 'vue'
import type { DockerTargetError } from '../../api'
import {
  useMonitorRuntimeState,
  type MonitorRuntimeOptions,
} from './useMonitorRuntimeState'

export type CardTagType = 'default' | 'info' | 'success' | 'warning' | 'error'
type CheckType = CardTagType

export interface MonitorCard {
  key: string
  label: string
  value: string
  help: string
  tag?: string
  tagType?: CardTagType
}

export interface HealthCheck {
  key: string
  label: string
  detail: string
  badge: string
  type: CheckType
}

type MonitorHealthOptions = MonitorRuntimeOptions & {
  dockerTargetErrors: Ref<DockerTargetError[]>
}

export function useMonitorHealth(options: MonitorHealthOptions) {
  const t = options.translate
  const runtime = useMonitorRuntimeState(options)
  const {
    activeTasks,
    linkedRunningContainers,
    longRunningTasks,
    orphanContainers,
    pendingQueuedTasks,
    recentFailureCount24h,
    recentFinishedCount24h,
    runningContainers,
    runningTasks,
    runningTasksWithoutContainer,
  } = runtime

  const healthChecks = computed<HealthCheck[]>(() => {
    const backlog = pendingQueuedTasks.value.length
    const running = runningTasks.value.length
    const missingContainers = runningTasksWithoutContainer.value.length
    const orphaned = orphanContainers.value.length
    const failures24h = recentFailureCount24h.value
    const unavailableTargets = options.dockerTargetErrors.value.length
    const workerNeedsReview =
      missingContainers > 0 || orphaned > 0 || unavailableTargets > 0
    return [
      {
        key: 'queue',
        label: t('monitor.queueHealthLabel'),
        detail:
          backlog > Math.max(6, running * 2)
            ? t('monitor.queueHealthHighDetail', { backlog })
            : t('monitor.queueHealthNormalDetail', { backlog }),
        badge:
          backlog > Math.max(6, running * 2)
            ? t('monitor.attention')
            : t('monitor.healthy'),
        type: backlog > Math.max(6, running * 2) ? 'warning' : 'success',
      },
      {
        key: 'workers',
        label: t('monitor.workerHealthLabel'),
        detail:
          workerNeedsReview
            ? t('monitor.workerHealthDegradedDetail', {
                missing: missingContainers,
                orphaned,
                unavailable: unavailableTargets,
              })
            : t('monitor.workerHealthAlignedDetail'),
        badge: workerNeedsReview ? t('monitor.needsReview') : t('monitor.aligned'),
        type: workerNeedsReview ? 'warning' : 'success',
      },
      {
        key: 'failures',
        label: t('monitor.failureHealthLabel'),
        detail:
          failures24h > 0
            ? t('monitor.failureHealthDetail', { count: failures24h })
            : t('monitor.failureHealthCleanDetail'),
        badge:
          failures24h > 2
            ? t('monitor.risky')
            : failures24h > 0
              ? t('monitor.watch')
              : t('monitor.stable'),
        type:
          failures24h > 2
            ? 'error'
            : failures24h > 0
              ? 'warning'
              : 'success',
      },
      {
        key: 'runtime',
        label: t('monitor.runtimeHealthLabel'),
        detail:
          longRunningTasks.value.length > 0
            ? t('monitor.runtimeHealthSlowDetail', {
                count: longRunningTasks.value.length,
              })
            : t('monitor.runtimeHealthNormalDetail'),
        badge:
          longRunningTasks.value.length > 0
            ? t('monitor.slow')
            : t('monitor.normal'),
        type: longRunningTasks.value.length > 0 ? 'warning' : 'success',
      },
    ]
  })
  const healthSummary = computed(() => {
    const types = healthChecks.value.map((check) => check.type)
    if (types.includes('error')) {
      return {
        label: t('monitor.healthNeedsAttention'),
        tag: t('monitor.risky'),
        tagType: 'error' as CardTagType,
      }
    }
    if (types.includes('warning')) {
      return {
        label: t('monitor.healthWatch'),
        tag: t('monitor.watch'),
        tagType: 'warning' as CardTagType,
      }
    }
    return {
      label: t('monitor.healthHealthy'),
      tag: t('monitor.healthy'),
      tagType: 'success' as CardTagType,
    }
  })
  const overviewCards = computed<MonitorCard[]>(() => [
    {
      key: 'running',
      label: t('monitor.runningNowLabel'),
      value: String(runningTasks.value.length),
      help: t('monitor.runningNowHelp', {
        containers: runningContainers.value.length,
      }),
      tag: t('monitor.live'),
      tagType: runningTasks.value.length > 0 ? 'warning' : 'default',
    },
    {
      key: 'backlog',
      label: t('monitor.backlogLabel'),
      value: String(pendingQueuedTasks.value.length),
      help: t('monitor.backlogHelp', {
        pending: options.stats.value.pending,
        queued: options.stats.value.queued,
      }),
      tag:
        pendingQueuedTasks.value.length > 0
          ? t('monitor.waiting')
          : t('monitor.clear'),
      tagType: pendingQueuedTasks.value.length > 6 ? 'warning' : 'info',
    },
    {
      key: 'containers',
      label: t('monitor.activeContainersLabel'),
      value: String(runningContainers.value.length),
      help: t('monitor.activeContainersHelp', {
        linked: linkedRunningContainers.value.length,
      }),
      tag:
        runningTasksWithoutContainer.value.length > 0 ||
        options.dockerTargetErrors.value.length > 0
          ? t('monitor.gaps')
          : t('monitor.aligned'),
      tagType:
        runningTasksWithoutContainer.value.length > 0 ||
        options.dockerTargetErrors.value.length > 0
          ? 'warning'
          : 'success',
    },
    {
      key: 'health',
      label: t('monitor.healthSummaryLabel'),
      value: healthSummary.value.label,
      help: t('monitor.healthSummaryHelp'),
      tag: healthSummary.value.tag,
      tagType: healthSummary.value.tagType,
    },
  ])
  const runtimeCards = computed<MonitorCard[]>(() => [
    {
      key: 'active',
      label: t('monitor.activeTasksMetric'),
      value: String(activeTasks.value.length),
      help: t('monitor.activeTasksMetricHelp'),
    },
    {
      key: 'completed24h',
      label: t('monitor.completed24hMetric'),
      value: String(recentFinishedCount24h.value),
      help: t('monitor.completed24hMetricHelp'),
    },
    {
      key: 'failures24h',
      label: t('monitor.failures24hMetric'),
      value: String(recentFailureCount24h.value),
      help: t('monitor.failures24hMetricHelp'),
    },
    {
      key: 'longRunning',
      label: t('monitor.longRunningMetric'),
      value: String(longRunningTasks.value.length),
      help: t('monitor.longRunningMetricHelp'),
    },
  ])
  const debugCards = computed<MonitorCard[]>(() => [
    {
      key: 'visible',
      label: t('monitor.visibleContainersMetric'),
      value: String(options.containers.value.length),
      help: t('monitor.visibleContainersMetricHelp'),
    },
    {
      key: 'linked',
      label: t('monitor.linkedContainersMetric'),
      value: String(linkedRunningContainers.value.length),
      help: t('monitor.linkedContainersMetricHelp'),
    },
    {
      key: 'missing',
      label: t('monitor.missingContainersMetric'),
      value: String(runningTasksWithoutContainer.value.length),
      help: t('monitor.missingContainersMetricHelp'),
    },
    {
      key: 'orphaned',
      label: t('monitor.orphanContainersMetric'),
      value: String(orphanContainers.value.length),
      help: t('monitor.orphanContainersMetricHelp'),
    },
  ])

  return {
    ...runtime,
    debugCards,
    healthChecks,
    healthSummary,
    overviewCards,
    runtimeCards,
  }
}
