export interface UsageLimitExceededItem {
  field: string
  window: 'daily' | 'weekly'
  metric: 'tokens' | 'tasks'
  used: number
  limit: number
  reset_at: string
}

export interface UsageLimitExceededDetail {
  reason: 'usage_limit_exceeded'
  scope: string
  exceeded_items: UsageLimitExceededItem[]
}

export function isUsageLimitExceededDetail(value: unknown): value is UsageLimitExceededDetail {
  if (!value || typeof value !== 'object') {
    return false
  }

  const detail = value as Partial<UsageLimitExceededDetail>
  return detail.reason === 'usage_limit_exceeded' && Array.isArray(detail.exceeded_items)
}

export function formatUsageResetAt(value: string) {
  const match = value.match(/^(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2})(?::\d{2})?(Z|[+-]\d{2}:\d{2})?$/)
  if (!match) {
    return value
  }

  const [, datePart, timePart, offset] = match
  let date: Date

  if (offset === 'Z') {
    date = new Date(`${datePart}T${timePart}:00Z`)
  } else if (offset) {
    date = new Date(`${datePart}T${timePart}:00${offset}`)
  } else {
    date = new Date(`${datePart}T${timePart}:00`)
  }

  const formatter = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })

  const parts = formatter.formatToParts(date)
  const get = (type: string) => parts.find((p) => p.type === type)?.value ?? ''
  const utc8Date = `${get('year')}-${get('month')}-${get('day')}`
  const utc8Time = `${get('hour')}:${get('minute')}`

  return `${utc8Date} ${utc8Time}`
}

export function toScientificNotation(value: number): string {
  if (value === 0) return '0'
  const exp = Math.floor(Math.log10(Math.abs(value)))
  if (exp < 6) return value.toLocaleString()
  const mantissa = value / Math.pow(10, exp)
  return `${mantissa.toFixed(2)}e${exp}`
}
