import { currentLocale } from '../i18n'

const UTC_PLUS_8_TIME_ZONE = 'Asia/Shanghai'

function getDateLocale(): string {
  return currentLocale.value === 'zh-CN' ? 'zh-CN' : 'en-GB'
}

function formatWithLocale(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions,
  timeZone?: string
): string {
  return new Intl.DateTimeFormat(getDateLocale(), {
    ...options,
    ...(timeZone ? { timeZone } : {})
  }).format(parseUtcDate(value))
}

function normalizeUtcInput(value: string | number | Date): string | number | Date {
  if (typeof value !== 'string') {
    return value
  }

  const hasTimezone = /(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  return hasTimezone ? value : `${value}Z`
}

export function parseUtcDate(value: string | number | Date): Date {
  return new Date(normalizeUtcInput(value))
}

export function formatDateTimeUtc8(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }
): string {
  return formatWithLocale(value, options, UTC_PLUS_8_TIME_ZONE)
}

export function formatDateTimeUtc8Compact(value: string | number | Date): string {
  return formatDateTimeUtc8(value, {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatMonthDayTimeUtc8(value: string | number | Date): string {
  return formatDateTimeUtc8(value, {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatMonthDayWeekdayUtc8(value: string | number | Date): string {
  return formatDateTimeUtc8(value, {
    month: '2-digit',
    day: '2-digit',
    weekday: 'short',
  })
}

export function formatTimeUtc8(value: string | number | Date): string {
  return formatDateTimeUtc8(value, {
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function formatDateTimeLocal(
  value: string | number | Date,
  options: Intl.DateTimeFormatOptions = {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }
): string {
  return formatWithLocale(value, options)
}

export function formatMonthDayLocal(value: string | number | Date): string {
  return formatDateTimeLocal(value, {
    month: '2-digit',
    day: '2-digit',
  })
}
