import { onMounted, onUnmounted, ref } from 'vue'

export interface UsePollingOptions {
  /** Polling interval in milliseconds */
  interval: number
  /** Call fn immediately when start() is invoked (default: true) */
  immediate?: boolean
  /** Skip polling ticks when the browser tab is not visible (default: true) */
  skipWhenHidden?: boolean
}

/**
 * Composable for polling a function at a fixed interval.
 *
 * Handles automatic cleanup on component unmount and optionally skips
 * ticks while the browser tab is hidden to avoid wasted requests.
 *
 * @example
 * ```ts
 * const { start, stop, isActive } = usePolling(
 *   () => { fetchTasks(); fetchStats() },
 *   { interval: 15_000 }
 * )
 *
 * onMounted(() => start())
 * ```
 */
export function usePolling(fn: () => void | Promise<void>, options: UsePollingOptions) {
  const isActive = ref(false)
  let timer: ReturnType<typeof setInterval> | null = null

  function start() {
    stop()
    isActive.value = true
    if (options.immediate !== false) {
      fn()
    }
    timer = setInterval(() => {
      if (options.skipWhenHidden !== false && document.visibilityState !== 'visible') return
      fn()
    }, options.interval)
  }

  function stop() {
    if (timer !== null) {
      clearInterval(timer)
      timer = null
    }
    isActive.value = false
  }

  function handleVisibilityChange() {
    if (
      options.skipWhenHidden === false ||
      !isActive.value ||
      document.visibilityState !== 'visible'
    ) {
      return
    }
    fn()
  }

  onMounted(() => {
    document.addEventListener('visibilitychange', handleVisibilityChange)
  })

  onUnmounted(() => {
    document.removeEventListener('visibilitychange', handleVisibilityChange)
    stop()
  })

  return { start, stop, isActive }
}
