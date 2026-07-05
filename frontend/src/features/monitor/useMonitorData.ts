import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getContainers,
  getStats,
  getTasks,
  getTasksPaginated,
  type Container,
  type Stats,
  type Task,
} from '../../api'

const EMPTY_STATS: Stats = {
  total: 0,
  pending: 0,
  queued: 0,
  running: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
  completed_24h: 0,
  failed_cancelled_24h: 0,
  running_long_30min: 0,
}

export function useMonitorData() {
  const message = useMessage()
  const { t } = useI18n()
  const loading = ref(false)
  const hasLoadedOnce = ref(false)
  const refreshRequestInFlight = ref(false)
  const stats = ref<Stats>({ ...EMPTY_STATS })
  const containers = ref<Container[]>([])
  const tasks = ref<Task[]>([])
  const recentFinishedList = ref<Task[]>([])
  const recentFailureList = ref<Task[]>([])
  const nowMs = ref(Date.now())
  let pendingSilentRefresh = false
  let pendingVisibleRefresh = false
  let refreshTimer: number | null = null
  let elapsedTimer: ReturnType<typeof setInterval> | null = null
  let disposed = false

  async function fetchData(options: { silent?: boolean } = {}) {
    if (disposed) return
    const silent = options.silent ?? false
    if (refreshRequestInFlight.value) {
      if (silent) pendingSilentRefresh = true
      else pendingVisibleRefresh = true
      return
    }

    refreshRequestInFlight.value = true
    if (!silent) loading.value = true
    try {
      const [statsData, containersData, tasksData, finishedResult, failedResult] =
        await Promise.all([
          getStats(),
          getContainers(),
          getTasks({ status: 'running,pending,queued' }),
          getTasksPaginated({
            status: 'completed,failed,cancelled',
            page: 1,
            page_size: 10,
          }),
          getTasksPaginated({
            status: 'failed,cancelled',
            page: 1,
            page_size: 10,
          }),
        ])

      if (!disposed) {
        stats.value = statsData
        containers.value = containersData
        tasks.value = tasksData
        recentFinishedList.value = finishedResult.items
        recentFailureList.value = failedResult.items
        hasLoadedOnce.value = true
      }
    } catch (error) {
      if (!disposed) {
        console.error(error)
        message.error(t('monitor.failedToFetchData'))
      }
    } finally {
      if (!silent) loading.value = false
      refreshRequestInFlight.value = false

      if (!disposed && (pendingVisibleRefresh || pendingSilentRefresh)) {
        const nextSilent = !pendingVisibleRefresh
        pendingVisibleRefresh = false
        pendingSilentRefresh = false
        await fetchData({ silent: nextSilent })
      }
    }
  }

  function stopAutoRefresh() {
    if (refreshTimer !== null) {
      window.clearInterval(refreshTimer)
      refreshTimer = null
    }
  }

  function startAutoRefresh() {
    if (disposed) return
    stopAutoRefresh()
    refreshTimer = window.setInterval(() => {
      void fetchData({ silent: true })
    }, 15000)
  }

  onMounted(async () => {
    disposed = false
    await fetchData()
    if (disposed) return
    startAutoRefresh()
    elapsedTimer = setInterval(() => {
      nowMs.value = Date.now()
    }, 1000)
  })

  onBeforeUnmount(() => {
    disposed = true
    pendingVisibleRefresh = false
    pendingSilentRefresh = false
    stopAutoRefresh()
    if (elapsedTimer) {
      clearInterval(elapsedTimer)
      elapsedTimer = null
    }
  })

  return {
    containers,
    fetchData,
    hasLoadedOnce,
    loading,
    nowMs,
    recentFailureList,
    recentFinishedList,
    refreshRequestInFlight,
    startAutoRefresh,
    stats,
    stopAutoRefresh,
    tasks,
  }
}
