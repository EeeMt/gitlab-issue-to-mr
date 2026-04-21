import type { ComposerTranslation } from 'vue-i18n'
import { formatDateTimeUtc8Compact, formatTimeUtc8, parseUtcDate } from './datetime'

interface SlotFullDetail {
  code: 'SLOT_FULL'
  hour_start: string
  hour_end: string
  count: number
  max: number
}

function isSlotFullDetail(detail: unknown): detail is SlotFullDetail {
  return (
    typeof detail === 'object' &&
    detail !== null &&
    (detail as Record<string, unknown>).code === 'SLOT_FULL'
  )
}

/**
 * Format a 409 slot-full error into a localized, timezone-correct message.
 * Returns null if the error is not a slot-full error.
 */
export function formatSlotError(
  detail: unknown,
  t: ComposerTranslation
): string | null {
  if (!isSlotFullDetail(detail)) return null

  const start = parseUtcDate(detail.hour_start)
  const end = parseUtcDate(detail.hour_end)

  return t('slotCapacity.slotFullError', {
    start: formatDateTimeUtc8Compact(start),
    end: formatTimeUtc8(end),
    count: detail.count,
    max: detail.max,
  })
}

/**
 * Extract error message from an axios error, with slot-full awareness.
 * Tries structured slot-full detail first, then string detail, then fallback.
 */
export function extractSlotErrorMessage(
  error: any,
  t: ComposerTranslation,
  fallbackKey: string
): string {
  const detail = error?.response?.data?.detail
  return formatSlotError(detail, t)
    ?? (typeof detail === 'string' ? detail : t(fallbackKey))
}
