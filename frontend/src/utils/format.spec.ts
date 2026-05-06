import { describe, it, expect } from 'vitest'
import {
  formatPriority,
  getProjectLabel,
  formatDurationMs,
  formatDurationSec,
  isSameLocalDay
} from './format'

describe('format utilities', () => {
  // ─── formatPriority ────────────────────────────────────────────────
  describe('formatPriority', () => {
    it('returns "-" for null', () => {
      expect(formatPriority(null)).toBe('-')
    })

    it('returns "-" for undefined', () => {
      expect(formatPriority(undefined)).toBe('-')
    })

    it('returns "-" for empty string', () => {
      expect(formatPriority('')).toBe('-')
    })

    it('returns "-" when called with no arguments', () => {
      expect(formatPriority()).toBe('-')
    })

    it.each([
      [0, 'P0'],
      ['0', 'P0'],
      ['p0', 'P0'],
      ['P0', 'P0'],
    ])('returns "P0" for input %s', (input, expected) => {
      expect(formatPriority(input)).toBe(expected)
    })

    it.each([
      [1, 'P1'],
      ['1', 'P1'],
      ['p1', 'P1'],
      ['P1', 'P1'],
    ])('returns "P1" for input %s', (input, expected) => {
      expect(formatPriority(input)).toBe(expected)
    })

    it.each([
      [2, 'P2'],
      ['2', 'P2'],
      ['p2', 'P2'],
      ['P2', 'P2'],
    ])('returns "P2" for input %s', (input, expected) => {
      expect(formatPriority(input)).toBe(expected)
    })

    it('returns String(priority) for unknown numeric value', () => {
      expect(formatPriority(5)).toBe('5')
    })

    it('returns String(priority) for unknown string value', () => {
      expect(formatPriority('custom')).toBe('custom')
    })

    it('handles whitespace-padded priority strings', () => {
      expect(formatPriority(' p1 ')).toBe('P1')
    })
  })

  // ─── getProjectLabel ───────────────────────────────────────────────
  describe('getProjectLabel', () => {
    it('returns project_path_with_namespace when available', () => {
      const task = {
        project_path_with_namespace: 'group/my-project',
        project_name: 'my-project',
        project_id: 42,
      }
      expect(getProjectLabel(task)).toBe('group/my-project')
    })

    it('returns project_name when path_with_namespace is null', () => {
      const task = {
        project_path_with_namespace: null,
        project_name: 'my-project',
        project_id: 42,
      }
      expect(getProjectLabel(task)).toBe('my-project')
    })

    it('returns project_name when path_with_namespace is undefined', () => {
      const task = {
        project_name: 'my-project',
        project_id: 42,
      } as { project_path_with_namespace?: string | null; project_name?: string | null; project_id: number }
      expect(getProjectLabel(task)).toBe('my-project')
    })

    it('returns fallback when both namespace and name are null', () => {
      const task = {
        project_path_with_namespace: null,
        project_name: null,
        project_id: 42,
      }
      expect(getProjectLabel(task, 'Fallback Label')).toBe('Fallback Label')
    })

    it('returns "Project #N" when no fallback is provided and both fields are null', () => {
      const task = {
        project_path_with_namespace: null,
        project_name: null,
        project_id: 99,
      }
      expect(getProjectLabel(task)).toBe('Project #99')
    })

    it('returns "Project #N" when fallback is undefined and both fields are null', () => {
      const task = {
        project_path_with_namespace: null,
        project_name: null,
        project_id: 7,
      }
      expect(getProjectLabel(task, undefined)).toBe('Project #7')
    })

    it('prefers path_with_namespace over project_name', () => {
      const task = {
        project_path_with_namespace: 'org/repo',
        project_name: 'repo',
        project_id: 1,
      }
      expect(getProjectLabel(task)).toBe('org/repo')
    })

    it('treats empty-string path_with_namespace as falsy and falls through', () => {
      const task = {
        project_path_with_namespace: '',
        project_name: 'my-project',
        project_id: 1,
      }
      expect(getProjectLabel(task)).toBe('my-project')
    })
  })

  // ─── formatDurationMs ─────────────────────────────────────────────
  describe('formatDurationMs', () => {
    it('returns "-" for 0', () => {
      expect(formatDurationMs(0)).toBe('-')
    })

    it('returns "-" for negative values', () => {
      expect(formatDurationMs(-1000)).toBe('-')
    })

    it('returns seconds for durations less than 60 000 ms', () => {
      expect(formatDurationMs(1)).toBe('0s')
      expect(formatDurationMs(30_000)).toBe('30s')
      expect(formatDurationMs(59_999)).toBe('59s')
    })

    it('returns "1m 0s" for exactly 60 000 ms', () => {
      expect(formatDurationMs(60_000)).toBe('1m 0s')
    })

    it('returns "5m 0s" for 300 000 ms', () => {
      expect(formatDurationMs(300_000)).toBe('5m 0s')
    })

    it('returns "1h 0m 0s" for exactly 1 hour', () => {
      expect(formatDurationMs(3_600_000)).toBe('1h 0m 0s')
    })

    it('returns "1h 30m 0s" for 5 400 000 ms', () => {
      expect(formatDurationMs(5_400_000)).toBe('1h 30m 0s')
    })

    it('returns "2h 30m 0s" for 9 000 000 ms', () => {
      expect(formatDurationMs(9_000_000)).toBe('2h 30m 0s')
    })
  })

  // ─── formatDurationSec ─────────────────────────────────────────────
  describe('formatDurationSec', () => {
    it('returns "—" (em-dash) for null', () => {
      expect(formatDurationSec(null)).toBe('—')
    })

    it('returns "—" for undefined', () => {
      expect(formatDurationSec(undefined)).toBe('—')
    })

    it('returns "—" for NaN', () => {
      expect(formatDurationSec(NaN)).toBe('—')
    })

    it('returns "0s" for 0', () => {
      expect(formatDurationSec(0)).toBe('0s')
    })

    it('returns "0s" for negative values (clamped to 0)', () => {
      expect(formatDurationSec(-10)).toBe('0s')
    })

    it('returns "45s" for 45', () => {
      expect(formatDurationSec(45)).toBe('45s')
    })

    it('returns "59s" for 59', () => {
      expect(formatDurationSec(59)).toBe('59s')
    })

    it('returns "1m" for exactly 60 seconds', () => {
      expect(formatDurationSec(60)).toBe('1m')
    })

    it('returns "5m" for 300 seconds', () => {
      expect(formatDurationSec(300)).toBe('5m')
    })

    it('returns "5m 30s" for 330 seconds', () => {
      expect(formatDurationSec(330)).toBe('5m 30s')
    })

    it('returns "1h" for exactly 3600 seconds', () => {
      expect(formatDurationSec(3600)).toBe('1h')
    })

    it('returns "1h 30m" for 5400 seconds', () => {
      expect(formatDurationSec(5400)).toBe('1h 30m')
    })

    it('returns "2h" for 7200 seconds', () => {
      expect(formatDurationSec(7200)).toBe('2h')
    })

    it('rounds fractional seconds before formatting', () => {
      // 59.6 rounds to 60 → "1m"
      expect(formatDurationSec(59.6)).toBe('1m')
      // 59.4 rounds to 59 → "59s"
      expect(formatDurationSec(59.4)).toBe('59s')
    })
  })

  // ─── isSameLocalDay ────────────────────────────────────────────────
  describe('isSameLocalDay', () => {
    it('returns true for the same date object', () => {
      const d = new Date(2025, 5, 15, 10, 30)
      expect(isSameLocalDay(d, d)).toBe(true)
    })

    it('returns true for two dates on the same calendar day', () => {
      const a = new Date(2025, 5, 15, 0, 0, 0)
      const b = new Date(2025, 5, 15, 23, 59, 59)
      expect(isSameLocalDay(a, b)).toBe(true)
    })

    it('returns false for adjacent days', () => {
      const a = new Date(2025, 5, 15, 23, 59, 59)
      const b = new Date(2025, 5, 16, 0, 0, 0)
      expect(isSameLocalDay(a, b)).toBe(false)
    })

    it('returns false for same day in different months', () => {
      const a = new Date(2025, 0, 15) // Jan 15
      const b = new Date(2025, 1, 15) // Feb 15
      expect(isSameLocalDay(a, b)).toBe(false)
    })

    it('returns false for same day and month in different years', () => {
      const a = new Date(2024, 5, 15)
      const b = new Date(2025, 5, 15)
      expect(isSameLocalDay(a, b)).toBe(false)
    })

    it('returns true for midnight and noon of the same day', () => {
      const a = new Date(2025, 0, 1, 0, 0, 0)
      const b = new Date(2025, 0, 1, 12, 0, 0)
      expect(isSameLocalDay(a, b)).toBe(true)
    })
  })
})
