import type { TaskScheduleWindow } from '../api'
import { parseUtcDate } from './datetime'

/**
 * Shape returned by the time-disabled predicate, mirroring naive-ui's
 * ``TimeValidator`` (``is-time-disabled`` prop). The runtime also passes the
 * currently selected hour to ``isMinuteDisabled(minute, hour)`` (naive-ui
 * time-picker Panel), so minutes can be narrowed to the boundary hour.
 */
export interface ScheduleTimeValidator {
  isHourDisabled?: (hour: number) => boolean
  isMinuteDisabled?: (minute: number, hour: number | null) => boolean
  isSecondDisabled?: (second: number) => boolean
}

function startOfLocalDay(ts: number): number {
  const d = new Date(ts)
  d.setHours(0, 0, 0, 0)
  return d.getTime()
}

/**
 * Build a naive-ui NDatePicker ``is-time-disabled`` validator from the
 * ``schedule-constraints`` window (spec §6.3). Day granularity alone lets a user
 * pick an out-of-window time and only learn about the conflict from a 409 on
 * submit; on the boundary days this disables hours/minutes outside
 * ``[min_scheduled_at, max_scheduled_at]`` so the picker surfaces the window
 * immediately.
 */
export function buildScheduleTimeDisabled(window: TaskScheduleWindow | null) {
  return (currentTime: number): ScheduleTimeValidator => {
    if (!window || window.has_valid_window === false) return {}
    const t = currentTime
    const dayStart = startOfLocalDay(t)
    const min = window.min_scheduled_at ? parseUtcDate(window.min_scheduled_at) : null
    const max = window.max_scheduled_at ? parseUtcDate(window.max_scheduled_at) : null
    const minOnDay = min && startOfLocalDay(min.getTime()) === dayStart ? min : null
    const maxOnDay = max && startOfLocalDay(max.getTime()) === dayStart ? max : null
    if (!minOnDay && !maxOnDay) return {}
    return {
      isHourDisabled: (hour) => {
        if (minOnDay && hour < minOnDay.getHours()) return true
        if (maxOnDay && hour > maxOnDay.getHours()) return true
        return false
      },
      isMinuteDisabled: (minute, hour) => {
        if (hour === null) return false
        if (minOnDay && hour === minOnDay.getHours() && minute < minOnDay.getMinutes()) {
          return true
        }
        if (maxOnDay && hour === maxOnDay.getHours() && minute > maxOnDay.getMinutes()) {
          return true
        }
        return false
      },
    }
  }
}
