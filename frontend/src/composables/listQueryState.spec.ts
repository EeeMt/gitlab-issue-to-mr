import { describe, expect, it } from 'vitest'

import type { FilterSortConfig } from './useFilterSort'
import {
  buildListRouteQuery,
  parseAllowedQueryValue,
  parsePositiveIntegerQueryValue,
  readListQueryState,
  routeQueriesEqual,
} from './listQueryState'

const config: FilterSortConfig = {
  storageKey: 'test:list-query',
  filterFields: [
    {
      key: 'status',
      label: 'Status',
      type: 'multi-select',
      parseValue: (value) => parseAllowedQueryValue(value, ['open', 'closed'] as const),
    },
    {
      key: 'project_id',
      label: 'Project',
      type: 'multi-select',
      parseValue: parsePositiveIntegerQueryValue,
    },
    { key: 'initiator', label: 'Initiator', type: 'multi-select' },
    {
      key: 'has_mr',
      label: 'MR',
      type: 'single-select',
      parseValue: (value) => parseAllowedQueryValue(value, ['true', 'false'] as const),
    },
    {
      key: 'created',
      label: 'Created',
      type: 'date-range',
      apiParam: 'created_after,created_before',
    },
  ],
  sortFields: [
    { key: 'created_at', label: 'Created' },
    { key: 'status', label: 'Status' },
  ],
  columns: [],
  defaultSort: { field: 'created_at', order: 'desc' },
}

describe('listQueryState', () => {
  it('parses filters, stable initiators, sort, search, and pagination from the URL', () => {
    const state = readListQueryState(config, {
      status: 'open,closed',
      project_id: '7,9',
      initiator: 'user:1,username:legacy',
      has_mr: 'true',
      created_after: '2026-01-01T00:00:00.000Z',
      created_before: '2026-01-31T00:00:00.000Z',
      sort_by: 'status',
      sort_order: 'asc',
      search: 'release',
      page: '3',
      page_size: '50',
    }, { pageSize: 20 })

    expect(state.filters.status).toEqual(['open', 'closed'])
    expect(state.filters.project_id).toEqual([7, 9])
    expect(state.filters.initiator).toEqual(['user:1', 'username:legacy'])
    expect(state.filters.has_mr).toBe('true')
    expect(state.filters.created).toEqual([
      Date.parse('2026-01-01T00:00:00.000Z'),
      Date.parse('2026-01-31T00:00:00.000Z'),
    ])
    expect(state.sort).toEqual({ field: 'status', order: 'asc' })
    expect(state.search).toBe('release')
    expect(state.page).toBe(3)
    expect(state.pageSize).toBe(50)
  })

  it('falls back for invalid sort, pagination, and typed filter values', () => {
    const state = readListQueryState(config, {
      project_id: 'not-a-number,0,Infinity,3',
      sort_by: 'invalid',
      sort_order: 'sideways',
      page: '-1',
      page_size: '500',
    }, { pageSize: 20 })

    expect(state.filters.project_id).toEqual([3])
    expect(state.sort).toEqual({ field: 'created_at', order: 'desc' })
    expect(state.page).toBe(1)
    expect(state.pageSize).toBe(100)
  })

  it('builds a canonical route query and compares query values consistently', () => {
    const query = buildListRouteQuery(
      { status: 'open,closed', sort_by: 'created_at', sort_order: 'desc' },
      'release',
      2,
      20,
    )

    expect(query).toEqual({
      status: 'open,closed',
      sort_by: 'created_at',
      sort_order: 'desc',
      search: 'release',
      page: '2',
      page_size: '20',
    })
    expect(routeQueriesEqual({ ...query }, query)).toBe(true)
    expect(routeQueriesEqual({ ...query, page: '3' }, query)).toBe(false)
  })

  it('preserves repeated multi-select query parameters', () => {
    const state = readListQueryState(config, {
      status: ['open', 'closed'],
      initiator: ['user:1', 'username:legacy'],
    }, { pageSize: 20 })

    expect(state.filters.status).toEqual(['open', 'closed'])
    expect(state.filters.initiator).toEqual(['user:1', 'username:legacy'])
  })

  it('rejects non-positive and non-finite identifier query values', () => {
    expect(parsePositiveIntegerQueryValue('7')).toBe(7)
    expect(parsePositiveIntegerQueryValue('0')).toBeUndefined()
    expect(parsePositiveIntegerQueryValue('-1')).toBeUndefined()
    expect(parsePositiveIntegerQueryValue('Infinity')).toBeUndefined()
  })

  it('accepts only allow-listed query values', () => {
    expect(parseAllowedQueryValue('open', ['open', 'closed'] as const)).toBe('open')
    expect(parseAllowedQueryValue('bogus', ['open', 'closed'] as const)).toBeUndefined()
  })

  it('trims URL search state and drops terms below the configured minimum', () => {
    const valid = readListQueryState(config, { search: '  release  ' }, {
      pageSize: 20,
      searchMinLength: 2,
    })
    const tooShort = readListQueryState(config, { search: ' x ' }, {
      pageSize: 20,
      searchMinLength: 2,
    })

    expect(valid.search).toBe('release')
    expect(tooShort.search).toBe('')
  })

  it('drops invalid static filter values so a canonical URL cannot preserve them', () => {
    const state = readListQueryState(config, {
      status: 'open,bogus',
      has_mr: 'yes',
    }, { pageSize: 20 })

    expect(state.filters.status).toEqual(['open'])
    expect(state.filters.has_mr).toBeUndefined()
  })

  it('keeps a valid one-sided date bound when the other URL bound is malformed', () => {
    const state = readListQueryState(config, {
      created_after: 'not-a-date',
      created_before: '2026-01-31T23:59:59.999Z',
    }, { pageSize: 20 })

    expect(state.filters.created).toEqual([
      null,
      Date.parse('2026-01-31T23:59:59.999Z'),
    ])
  })

  it('drops a reversed URL date range', () => {
    const state = readListQueryState(config, {
      created_after: '2026-02-01T00:00:00.000Z',
      created_before: '2026-01-01T00:00:00.000Z',
    }, { pageSize: 20 })

    expect(state.filters.created).toBeUndefined()
  })
})
