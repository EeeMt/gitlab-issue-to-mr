import { describe, it, expect } from 'vitest'
import { buildScheduleTimeDisabled } from './scheduleWindow'

const WINDOW = {
  has_valid_window: true,
  min_scheduled_at: '2026-04-01T10:00:00Z',
  max_scheduled_at: '2026-04-01T18:00:00Z',
  min_source_task_id: 1,
  max_source_task_id: 2,
}

describe('buildScheduleTimeDisabled', () => {
  it('disables hours before the min boundary on the min day', () => {
    const isDisabled = buildScheduleTimeDisabled(WINDOW)
    const min = new Date('2026-04-01T10:00:00Z')
    const validator = isDisabled(min.getTime())
    expect(validator.isHourDisabled?.(min.getHours() - 1)).toBe(true)
    expect(validator.isHourDisabled?.(min.getHours() + 1)).toBe(false)
  })

  it('disables hours after the max boundary on the max day', () => {
    const isDisabled = buildScheduleTimeDisabled(WINDOW)
    const max = new Date('2026-04-01T18:00:00Z')
    const validator = isDisabled(max.getTime())
    expect(validator.isHourDisabled?.(max.getHours() + 1)).toBe(true)
    expect(validator.isHourDisabled?.(max.getHours() - 1)).toBe(false)
  })

  it('allows every time on days strictly inside the window', () => {
    const isDisabled = buildScheduleTimeDisabled(WINDOW)
    // Far enough from the boundary days that no timezone shift makes it a
    // min/max boundary day.
    const validator = isDisabled(new Date('2026-04-08T00:00:00Z').getTime())
    expect(validator).toEqual({})
  })

  it('returns an empty validator when there is no valid window', () => {
    const isDisabled = buildScheduleTimeDisabled({
      has_valid_window: false,
      min_scheduled_at: null,
      max_scheduled_at: null,
      min_source_task_id: null,
      max_source_task_id: null,
    })
    expect(isDisabled(new Date('2026-04-01T09:00:00Z').getTime())).toEqual({})
  })

  it('returns an empty validator when constraints are absent', () => {
    const isDisabled = buildScheduleTimeDisabled(null)
    expect(isDisabled(new Date('2026-04-01T09:00:00Z').getTime())).toEqual({})
  })

  it('honors a min-only floor at minute precision on its boundary day', () => {
    const isDisabled = buildScheduleTimeDisabled({
      has_valid_window: true,
      min_scheduled_at: '2026-04-05T08:30:00Z',
      max_scheduled_at: null,
      min_source_task_id: 3,
      max_source_task_id: null,
    })
    const min = new Date('2026-04-05T08:30:00Z')
    const validator = isDisabled(min.getTime())
    expect(validator.isHourDisabled?.(min.getHours() - 1)).toBe(true)
    expect(validator.isMinuteDisabled?.(0, min.getHours())).toBe(true)
    expect(validator.isMinuteDisabled?.(40, min.getHours())).toBe(false)
  })

  it('honors a max-only ceiling at minute precision on its boundary day', () => {
    const isDisabled = buildScheduleTimeDisabled({
      has_valid_window: true,
      min_scheduled_at: null,
      max_scheduled_at: '2026-04-06T17:45:00Z',
      min_source_task_id: null,
      max_source_task_id: 4,
    })
    const max = new Date('2026-04-06T17:45:00Z')
    const validator = isDisabled(max.getTime())
    expect(validator.isHourDisabled?.(max.getHours() + 1)).toBe(true)
    expect(validator.isMinuteDisabled?.(50, max.getHours())).toBe(true)
    expect(validator.isMinuteDisabled?.(30, max.getHours())).toBe(false)
  })

  it('clamps both ends when the window fits within one local day', () => {
    const isDisabled = buildScheduleTimeDisabled({
      has_valid_window: true,
      min_scheduled_at: '2026-04-09T02:30:00Z',
      max_scheduled_at: '2026-04-09T06:15:00Z',
      min_source_task_id: 5,
      max_source_task_id: 6,
    })
    const min = new Date('2026-04-09T02:30:00Z')
    const max = new Date('2026-04-09T06:15:00Z')
    const validator = isDisabled(min.getTime())
    expect(validator.isHourDisabled?.(min.getHours() - 1)).toBe(true)
    expect(validator.isHourDisabled?.(max.getHours() + 1)).toBe(true)
    expect(validator.isHourDisabled?.(min.getHours())).toBe(false)
    expect(validator.isMinuteDisabled?.(0, min.getHours())).toBe(true)
    expect(validator.isMinuteDisabled?.(40, min.getHours())).toBe(false)
  })
})
