import { describe, it, expect, vi, beforeEach } from 'vitest'
import { ref } from 'vue'
import {
  parseUtcDate,
  formatDateTimeUtc8,
  formatDateTimeUtc8Compact
} from './datetime'
import { currentLocale } from '../i18n'

// Mock i18n currentLocale
vi.mock('../i18n', async () => {
  const actual = await vi.importActual('../i18n')
  return {
    ...actual,
    currentLocale: ref('en')
  }
})

describe('datetime utilities', () => {
  describe('parseUtcDate', () => {
    it('should parse ISO string with Z suffix', () => {
      const result = parseUtcDate('2026-03-31T10:00:00Z')
      expect(result).toBeInstanceOf(Date)
      expect(result.toISOString()).toBe('2026-03-31T10:00:00.000Z')
    })

    it('should parse ISO string without Z suffix', () => {
      const result = parseUtcDate('2026-03-31T10:00:00')
      expect(result).toBeInstanceOf(Date)
      expect(result.toISOString()).toBe('2026-03-31T10:00:00.000Z')
    })

    it('should handle Date object', () => {
      const date = new Date('2026-03-31T10:00:00Z')
      const result = parseUtcDate(date)
      expect(result).toBeInstanceOf(Date)
      expect(result.toISOString()).toBe('2026-03-31T10:00:00.000Z')
    })

    it('should handle timestamp', () => {
      // Use a Date object to derive a known timestamp
      const date = new Date('2026-03-31T10:00:00Z')
      const timestamp = date.getTime()
      const result = parseUtcDate(timestamp)
      expect(result).toBeInstanceOf(Date)
      // Verify the result matches the original date
      expect(result.toISOString()).toBe(date.toISOString())
    })
  })

  describe('formatDateTimeUtc8', () => {
    beforeEach(() => {
      // Reset locale to English for consistent tests
      currentLocale.value = 'en'
    })

    it('should format datetime in UTC+8 timezone', () => {
      const result = formatDateTimeUtc8('2026-03-31T02:00:00Z')
      // UTC+8 is 8 hours ahead of UTC, so 02:00 UTC = 10:00 UTC+8
      expect(result).toContain('2026')
      expect(result).toContain('31')
      expect(result).toContain('10') // hour in UTC+8
    })

    it('should use locale-specific format', () => {
      // Test English locale
      currentLocale.value = 'en'
      const enResult = formatDateTimeUtc8('2026-03-31T02:00:00Z')
      expect(enResult).toBeDefined()

      // Test Chinese locale
      currentLocale.value = 'zh-CN'
      const zhResult = formatDateTimeUtc8('2026-03-31T02:00:00Z')
      expect(zhResult).toBeDefined()
    })

    it('should format with custom options', () => {
      const result = formatDateTimeUtc8('2026-03-31T02:00:00Z', {
        year: 'numeric',
        month: 'short',
        day: 'numeric'
      })
      expect(result).toContain('2026')
    })
  })

  describe('formatDateTimeUtc8Compact', () => {
    beforeEach(() => {
      currentLocale.value = 'en'
    })

    it('should format datetime without seconds', () => {
      const result = formatDateTimeUtc8Compact('2026-03-31T02:00:00Z')
      // Should not contain seconds
      expect(result).not.toMatch(/:\d{2}:\d{2}/)
      // Should contain date and time
      expect(result).toContain('2026')
      expect(result).toContain('31')
    })

    it('should format in UTC+8 timezone', () => {
      const result = formatDateTimeUtc8Compact('2026-03-31T02:00:00Z')
      // UTC+8: 02:00 UTC = 10:00 UTC+8
      expect(result).toContain('10')
    })
  })
})
