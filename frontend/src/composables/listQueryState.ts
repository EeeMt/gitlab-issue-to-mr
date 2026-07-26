import type { LocationQuery, LocationQueryRaw } from 'vue-router'

import type { FilterSortConfig } from './useFilterSort'

export interface ListQueryState {
  filters: Record<string, any>
  sort: { field: string; order: 'asc' | 'desc' }
  search: string
  page: number
  pageSize: number
}

function firstQueryValue(value: LocationQuery[string]): string | undefined {
  if (Array.isArray(value)) return value[0] ?? undefined
  return value ?? undefined
}

function multiQueryValue(value: LocationQuery[string]): string | undefined {
  if (Array.isArray(value)) {
    const values = value.filter((item): item is string => item !== null && item !== '')
    return values.length ? values.join(',') : undefined
  }
  return value ?? undefined
}

function positiveInteger(value: string | undefined, fallback: number): number {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : fallback
}

export function parsePositiveIntegerQueryValue(value: string): number | undefined {
  const parsed = Number(value)
  return Number.isInteger(parsed) && parsed > 0 ? parsed : undefined
}

export function parseAllowedQueryValue<T extends string>(
  value: string,
  allowedValues: readonly T[],
): T | undefined {
  return allowedValues.includes(value as T) ? value as T : undefined
}

export function readListQueryState(
  config: FilterSortConfig,
  query: LocationQuery,
  defaults: { pageSize: number; searchMinLength?: number },
): ListQueryState {
  const filters: Record<string, any> = {}

  for (const field of config.filterFields) {
    if (field.type === 'date-range' && field.apiParam) {
      const [afterKey, beforeKey] = field.apiParam.split(',').map((key) => key.trim())
      const after = firstQueryValue(query[afterKey])
      const before = firstQueryValue(query[beforeKey])
      if (after || before) {
        const afterTime = after ? Date.parse(after) : Number.NaN
        const beforeTime = before ? Date.parse(before) : Number.NaN
        const parsedAfter = Number.isFinite(afterTime) ? afterTime : null
        const parsedBefore = Number.isFinite(beforeTime) ? beforeTime : null
        if (
          (parsedAfter !== null || parsedBefore !== null)
          && !(parsedAfter !== null && parsedBefore !== null && parsedAfter > parsedBefore)
        ) {
          filters[field.key] = [parsedAfter, parsedBefore]
        }
      }
      continue
    }

    const queryKey = field.apiParam ?? field.key
    const rawValue = field.type === 'multi-select'
      ? multiQueryValue(query[queryKey])
      : firstQueryValue(query[queryKey])
    if (rawValue === undefined || rawValue === '') continue

    if (field.type === 'multi-select') {
      const values = rawValue
        .split(',')
        .map((value) => value.trim())
        .filter(Boolean)
        .map((value) => field.parseValue ? field.parseValue(value) : value)
        .filter((value) => value !== undefined && (
          typeof value !== 'number' || Number.isFinite(value)
        ))
      if (values.length) filters[field.key] = values
    } else {
      const parsedValue = field.parseValue ? field.parseValue(rawValue) : rawValue
      if (parsedValue !== undefined && (
        typeof parsedValue !== 'number' || Number.isFinite(parsedValue)
      )) {
        filters[field.key] = parsedValue
      }
    }
  }

  const requestedSort = firstQueryValue(query.sort_by)
  const requestedOrder = firstQueryValue(query.sort_order)
  const sortField = config.sortFields.some((field) => field.key === requestedSort)
    ? requestedSort!
    : config.defaultSort.field
  const sortOrder = requestedOrder === 'asc' || requestedOrder === 'desc'
    ? requestedOrder
    : config.defaultSort.order

  const search = (firstQueryValue(query.search) ?? '').trim()
  const searchMinLength = Math.max(1, defaults.searchMinLength ?? 1)

  return {
    filters,
    sort: { field: sortField, order: sortOrder },
    search: search.length >= searchMinLength ? search : '',
    page: positiveInteger(firstQueryValue(query.page), 1),
    pageSize: Math.min(100, positiveInteger(firstQueryValue(query.page_size), defaults.pageSize)),
  }
}

export function buildListRouteQuery(
  apiParams: Record<string, string>,
  search: string,
  page: number,
  pageSize: number,
): LocationQueryRaw {
  return {
    ...apiParams,
    ...(search ? { search } : {}),
    page: String(page),
    page_size: String(pageSize),
  }
}

export function routeQueriesEqual(left: LocationQuery, right: LocationQueryRaw): boolean {
  const normalize = (query: LocationQuery | LocationQueryRaw) => Object.keys(query)
    .sort()
    .map((key) => {
      const value = query[key]
      return [key, Array.isArray(value) ? value.map(String).join(',') : String(value ?? '')]
    })
  return JSON.stringify(normalize(left)) === JSON.stringify(normalize(right))
}
