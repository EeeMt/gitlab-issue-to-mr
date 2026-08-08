import type { ComposerTranslation } from 'vue-i18n'
import type { TaskConflictDetail } from '../api'
import { formatDateTimeUtc8Compact, parseUtcDate } from './datetime'

const TASK_CONFLICT_CODES = new Set([
  'issue_schedule_order_conflict',
  'issue_sequence_repair_required',
  'issue_lineage_conflict',
  'retry_lineage_conflict',
])

function formatTimeLabel(value: string | null | undefined): string {
  if (!value) return ''
  try {
    return formatDateTimeUtc8Compact(parseUtcDate(value))
  } catch {
    return value
  }
}

/**
 * Format a structured 409 Issue-ordering conflict into a localized message.
 * Returns null when the detail is not an object envelope (so the caller can
 * fall back to a string detail); unknown codes surface ``detail.message``.
 */
export function formatTaskConflict(
  detail: unknown,
  t: ComposerTranslation,
): string | null {
  if (typeof detail !== 'object' || detail === null) return null
  const conflict = detail as TaskConflictDetail
  if (typeof conflict.code !== 'string') return null
  if (!TASK_CONFLICT_CODES.has(conflict.code)) {
    return conflict.message ?? null
  }

  switch (conflict.code) {
    case 'issue_schedule_order_conflict': {
      if (conflict.has_valid_window === false) {
        return t('scheduleConflict.noValidWindow')
      }
      const min = conflict.min_scheduled_at
      const max = conflict.max_scheduled_at
      if (min && !max && conflict.min_source_task_id != null) {
        return t('scheduleConflict.beforeFloor', {
          time: formatTimeLabel(min),
          source: conflict.min_source_task_id,
        })
      }
      if (max && !min && conflict.max_source_task_id != null) {
        return t('scheduleConflict.afterCeiling', {
          time: formatTimeLabel(max),
          source: conflict.max_source_task_id,
        })
      }
      if (min && max) {
        return t('scheduleConflict.windowBounds', {
          min: formatTimeLabel(min),
          max: formatTimeLabel(max),
        })
      }
      return conflict.message ?? t('scheduleConflict.generic')
    }
    case 'issue_lineage_conflict':
    case 'retry_lineage_conflict':
      return t('scheduleConflict.lineageMismatch')
    case 'issue_sequence_repair_required':
      return t('scheduleConflict.sequenceRepairRequired')
    default:
      return conflict.message ?? t('scheduleConflict.generic')
  }
}

/**
 * Extract a localized conflict message from an axios error.
 *
 * Only parses the object detail envelope produced by the backend's structured
 * 409 responses; falls back to a string detail, then to the caller's fallback
 * key. Unknown codes surface ``detail.message`` so an object is never rendered
 * as ``[object Object]``.
 */
export function extractTaskConflict(
  error: unknown,
  t: ComposerTranslation,
  fallbackKey: string,
): string {
  const detail = (error as any)?.response?.data?.detail
  return (
    formatTaskConflict(detail, t)
    ?? (typeof detail === 'string' ? detail : t(fallbackKey))
  )
}
