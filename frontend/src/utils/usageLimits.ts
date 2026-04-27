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
  if (!offset) {
    return `${datePart} ${timePart}`
  }

  const zoneLabel = offset === 'Z' ? 'UTC' : `UTC${offset}`
  return `${datePart} ${timePart} ${zoneLabel}`
}
