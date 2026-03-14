const UTC_PLUS_8_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai',
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
  hour12: false,
})

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

export function formatDateTimeUtc8(value: string | number | Date): string {
  return UTC_PLUS_8_FORMATTER.format(parseUtcDate(value))
}
