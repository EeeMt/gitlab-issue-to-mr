/**
 * Shared formatting utilities extracted from Vue components
 * to eliminate duplication across the codebase.
 */

/**
 * Normalise a task priority value to a human-readable label.
 * Handles numbers (0–2), strings ("p0"–"p2"), and null/undefined.
 */
export function formatPriority(priority?: string | number | null): string {
  if (priority === null || priority === undefined || priority === '') {
    return '-'
  }

  const normalized = String(priority).toLowerCase().trim()
  if (normalized === '0' || normalized === 'p0') return 'P0'
  if (normalized === '1' || normalized === 'p1') return 'P1'
  if (normalized === '2' || normalized === 'p2') return 'P2'
  return String(priority)
}

/**
 * Return the best available display label for a task's project.
 *
 * @param task      – must carry `project_path_with_namespace`, `project_name`, and `project_id`
 * @param fallback  – optional fallback string when neither name is available
 *                    (e.g. `t('dashboard.projectFallback', { id: task.project_id })`)
 */
export function getProjectLabel(
  task: { project_path_with_namespace?: string | null; project_name?: string | null; project_id: number },
  fallback?: string,
): string {
  return task.project_path_with_namespace || task.project_name || fallback || `Project #${task.project_id}`
}

/**
 * Format a duration given in **milliseconds** to a compact string.
 *
 * Examples: "2h 30m", "30m", "< 1m", "-" (for ≤ 0)
 *
 * Used by Monitor.vue for age / execution-duration display.
 */
export function formatDurationMs(milliseconds: number): string {
  if (milliseconds <= 0) return '-'

  const totalSeconds = Math.floor(milliseconds / 1000)
  const hours = Math.floor(totalSeconds / 3600)
  const minutes = Math.floor((totalSeconds % 3600) / 60)
  const seconds = totalSeconds % 60

  if (hours > 0) {
    return `${hours}h ${minutes}m ${seconds}s`
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`
  }
  return `${seconds}s`
}

/**
 * Format a duration given in **seconds** (nullable) to a compact string.
 *
 * Examples: "45s", "30m", "2h 30m", "—" (em-dash for null/NaN)
 *
 * Used by Analytics.vue for execution / queue-wait statistics.
 */
export function formatDurationSec(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return '—'
  }

  const seconds = Math.max(Math.round(value), 0)
  if (seconds < 60) {
    return `${seconds}s`
  }

  if (seconds < 3600) {
    const minutes = Math.floor(seconds / 60)
    const remainder = seconds % 60
    return remainder === 0 ? `${minutes}m` : `${minutes}m ${remainder}s`
  }

  const hours = Math.floor(seconds / 3600)
  const minutes = Math.floor((seconds % 3600) / 60)
  return minutes === 0 ? `${hours}h` : `${hours}h ${minutes}m`
}

/**
 * Check whether two Date objects fall on the same local calendar day.
 */
export function isSameLocalDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
  )
}
