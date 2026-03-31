import { vi } from 'vitest'

export const mockI18n = {
  t: vi.fn((key: string) => key),
  locale: { value: 'en' },
  d: vi.fn((value: unknown) => String(value)),
  n: vi.fn((value: number) => String(value)),
  te: vi.fn((key: string) => false)
}

export const createI18nMock = () => mockI18n
