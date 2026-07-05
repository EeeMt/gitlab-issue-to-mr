import { computed, nextTick, ref, watch, type ComputedRef, type Ref } from 'vue'
import type { Task } from '../../api'
import { formatTimeUtc8, parseUtcDate } from '../../utils/datetime'

export type MonitorTimelineZoom = 'auto' | '1h' | '2h' | '4h' | '8h' | '24h'

interface MonitorTimelineOptions {
  activeTasks: ComputedRef<Task[]>
  nowMs: Ref<number>
}

export function useMonitorTimeline(options: MonitorTimelineOptions) {
  const timelineZoom = ref<MonitorTimelineZoom>('auto')
  const timelineScrollRef = ref<{ $el?: HTMLElement } | null>(null)
  const timelineZoomOptions = [
    { label: 'Auto', value: 'auto' as const },
    { label: '1h', value: '1h' as const },
    { label: '2h', value: '2h' as const },
    { label: '4h', value: '4h' as const },
    { label: '8h', value: '8h' as const },
    { label: '24h', value: '24h' as const },
  ]

  const timelineRange = computed(() => {
    const now = options.nowMs.value
    let minTime = now - 60 * 60 * 1000
    let maxTime = now + 4 * 60 * 60 * 1000

    for (const task of options.activeTasks.value) {
      if (task.started_at) {
        minTime = Math.min(minTime, parseUtcDate(task.started_at).getTime())
      }
      if (task.scheduled_at) {
        const scheduledTime = parseUtcDate(task.scheduled_at).getTime()
        minTime = Math.min(minTime, scheduledTime)
        maxTime = Math.max(maxTime, scheduledTime + 30 * 60 * 1000)
      }
    }

    if (timelineZoom.value !== 'auto') {
      const windowMs = Number.parseInt(timelineZoom.value) * 60 * 60 * 1000
      minTime = Math.min(minTime, now - windowMs * 0.3)
      maxTime = Math.max(maxTime, now + windowMs * 0.7)
    }

    const span = maxTime - minTime
    const pad = span * 0.05
    return { start: minTime - pad, end: maxTime + pad }
  })

  function timelinePct(timeMs: number): number {
    const { start, end } = timelineRange.value
    const span = end - start
    if (span <= 0) return 0
    return Math.max(0, Math.min(100, ((timeMs - start) / span) * 100))
  }

  const timelineTicks = computed(() => {
    const { start, end } = timelineRange.value
    const span = end - start
    const intervals = [15, 30, 60, 120, 240]
    let intervalMin = 60

    if (timelineZoom.value !== 'auto') {
      const zoomMs = Number.parseInt(timelineZoom.value) * 60 * 60 * 1000
      for (const interval of intervals) {
        if (zoomMs / (interval * 60 * 1000) <= 8) {
          intervalMin = interval
          break
        }
      }
    } else {
      for (const interval of intervals) {
        if (span / (interval * 60 * 1000) <= 8) {
          intervalMin = interval
          break
        }
      }
    }

    const intervalMs = intervalMin * 60 * 1000
    const firstTick = Math.ceil(start / intervalMs) * intervalMs
    const ticks: { time: number; pct: number; label: string }[] = []
    for (let time = firstTick; time <= end; time += intervalMs) {
      ticks.push({
        time,
        pct: timelinePct(time),
        label: formatTimeUtc8(new Date(time)),
      })
    }
    return ticks
  })

  const timelineContainerMinWidth = computed(
    () => `${Math.max(600, timelineTicks.value.length * 90)}px`,
  )

  function scrollTimelineToNow() {
    const element = timelineScrollRef.value?.$el
    if (!element) return
    const scrollElement =
      (element.querySelector('.n-scrollbar-container') as HTMLElement) || element
    const nowPosition = (timelinePct(options.nowMs.value) / 100) * scrollElement.scrollWidth
    scrollElement.scrollLeft = nowPosition - scrollElement.clientWidth / 2
  }

  watch(timelineZoom, () => {
    void nextTick(scrollTimelineToNow)
  })

  return {
    scrollTimelineToNow,
    timelineContainerMinWidth,
    timelinePct,
    timelineRange,
    timelineScrollRef,
    timelineTicks,
    timelineZoom,
    timelineZoomOptions,
  }
}
