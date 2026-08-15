import { describe, expect, it, vi } from 'vitest'
import { extractTaskConflict, formatTaskConflict } from './taskConflict'

vi.mock('./datetime', () => ({
  parseUtcDate: vi.fn((value: string) => new Date(value)),
  formatDateTimeUtc8Compact: vi.fn(() => '2026-08-08 18:00'),
}))

const t = vi.fn((key: string, params?: Record<string, unknown>) => {
  const templates: Record<string, string> = {
    'scheduleConflict.noValidWindow': 'no-valid-window',
    'scheduleConflict.beforeFloor': 'before {time} #{source}',
    'scheduleConflict.afterCeiling': 'after {time} #{source}',
    'scheduleConflict.windowBounds': 'window {min} {max}',
    'scheduleConflict.lineageMismatch': 'lineage-mismatch',
    'scheduleConflict.sequenceRepairRequired': 'sequence-repair',
    'scheduleConflict.generic': 'generic',
    'taskView.failedToRescheduleTask': 'reschedule-failed',
  }
  const tmpl = templates[key] ?? key
  return tmpl.replace(/\{(\w+)\}/g, (_match, name) => String(params?.[name] ?? `{${name}}`))
})

describe('formatTaskConflict', () => {
  it('returns null for non-issue-ordering details', () => {
    expect(formatTaskConflict({ code: 'SLOT_FULL' }, t)).toBeNull()
    expect(formatTaskConflict('oops', t)).toBeNull()
    expect(formatTaskConflict(null, t)).toBeNull()
    expect(formatTaskConflict(undefined, t)).toBeNull()
  })

  it('maps an invalid window to the no-valid-window message', () => {
    const msg = formatTaskConflict({
      code: 'issue_schedule_order_conflict',
      has_valid_window: false,
      min_scheduled_at: '2026-08-08T14:00:00',
      max_scheduled_at: '2026-08-08T10:00:00',
    }, t)
    expect(msg).toBe('no-valid-window')
  })

  it('maps a single lower bound to the before-floor message', () => {
    const msg = formatTaskConflict({
      code: 'issue_schedule_order_conflict',
      has_valid_window: true,
      min_scheduled_at: '2026-08-08T10:00:00',
      min_source_task_id: 101,
      max_scheduled_at: null,
      max_source_task_id: null,
    }, t)
    expect(msg).toBe('before 2026-08-08 18:00 #101')
  })

  it('maps a single upper bound to the after-ceiling message', () => {
    const msg = formatTaskConflict({
      code: 'issue_schedule_order_conflict',
      has_valid_window: true,
      min_scheduled_at: null,
      min_source_task_id: null,
      max_scheduled_at: '2026-08-08T10:00:00',
      max_source_task_id: 103,
    }, t)
    expect(msg).toBe('after 2026-08-08 18:00 #103')
  })

  it('maps both bounds to the window-bounds message', () => {
    const msg = formatTaskConflict({
      code: 'issue_schedule_order_conflict',
      has_valid_window: true,
      min_scheduled_at: '2026-08-08T10:00:00',
      min_source_task_id: 101,
      max_scheduled_at: '2026-08-08T14:00:00',
      max_source_task_id: 103,
    }, t)
    expect(msg).toBe('window 2026-08-08 18:00 2026-08-08 18:00')
  })

  it('maps lineage conflicts to the lineage-mismatch message', () => {
    expect(formatTaskConflict({ code: 'issue_lineage_conflict', message: 'raw' }, t)).toBe('lineage-mismatch')
    expect(formatTaskConflict({ code: 'retry_lineage_conflict', message: 'raw' }, t)).toBe('lineage-mismatch')
  })

  it('maps repair-required to its message', () => {
    expect(formatTaskConflict({ code: 'issue_sequence_repair_required' }, t)).toBe('sequence-repair')
  })

  it('falls back to detail.message for unknown codes', () => {
    const msg = formatTaskConflict({ code: 'some_unknown_code', message: 'raw message' }, t)
    expect(msg).toBe('raw message')
  })
})

describe('extractTaskConflict', () => {
  it('parses the object detail envelope from the response', () => {
    const error = {
      response: {
        data: {
          detail: {
            code: 'issue_schedule_order_conflict',
            has_valid_window: false,
          },
        },
      },
    }
    expect(extractTaskConflict(error, t, 'taskView.failedToRescheduleTask')).toBe('no-valid-window')
  })

  it('passes through a string detail', () => {
    const error = { response: { data: { detail: 'plain error' } } }
    expect(extractTaskConflict(error, t, 'taskView.failedToRescheduleTask')).toBe('plain error')
  })

  it('falls back to the provided key when no detail is present', () => {
    expect(extractTaskConflict({ response: { data: {} } }, t, 'taskView.failedToRescheduleTask'))
      .toBe('reschedule-failed')
    expect(extractTaskConflict({}, t, 'taskView.failedToRescheduleTask')).toBe('reschedule-failed')
  })

  it('never returns an object for unknown codes without a message', () => {
    const error = {
      response: {
        data: {
          detail: { code: 'mystery_code' },
        },
      },
    }
    const msg = extractTaskConflict(error, t, 'taskView.failedToRescheduleTask')
    expect(typeof msg).toBe('string')
    expect(msg).not.toContain('[object Object]')
  })
})
