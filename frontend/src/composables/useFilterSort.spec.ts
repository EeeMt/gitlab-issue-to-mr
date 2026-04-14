import { describe, it, expect, beforeEach, vi } from 'vitest'
import { nextTick } from 'vue'
import { useFilterSort, type FilterSortConfig, type FilterField, type SortField, type ColumnDef } from './useFilterSort'

const mockConfig: FilterSortConfig = {
  storageKey: 'codify:filters:test',
  filterFields: [
    { key: 'status', label: 'Status', type: 'multi-select', options: () => [
      { label: 'Open', value: 'open' },
      { label: 'Closed', value: 'closed' },
    ] },
    { key: 'project_id', label: 'Project', type: 'single-select', options: () => [
      { label: 'App', value: 1 },
    ] },
  ] as FilterField[],
  sortFields: [
    { key: 'created_at', label: 'Created' },
    { key: 'status', label: 'Status' },
  ] as SortField[],
  columns: [
    { key: 'title', label: 'Title', defaultVisible: true, alwaysVisible: true },
    { key: 'status', label: 'Status', defaultVisible: true },
    { key: 'project', label: 'Project', defaultVisible: true },
    { key: 'creator', label: 'Creator', defaultVisible: false },
  ] as ColumnDef[],
  defaultSort: { field: 'created_at', order: 'desc' },
}

describe('useFilterSort', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('initializes with empty filters and default sort', () => {
    const { filters, sort, activeFilterCount } = useFilterSort(mockConfig)
    expect(filters.value).toEqual({})
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
    expect(activeFilterCount.value).toBe(0)
  })

  it('adds and removes a filter', () => {
    const { filters, addFilter, removeFilter, activeFilterCount } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    expect(filters.value.status).toEqual(['open'])
    expect(activeFilterCount.value).toBe(1)

    removeFilter('status')
    expect(filters.value.status).toBeUndefined()
    expect(activeFilterCount.value).toBe(0)
  })

  it('clears all filters', () => {
    const { filters, addFilter, clearAllFilters } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    addFilter('project_id', 1)
    clearAllFilters()
    expect(filters.value).toEqual({})
  })

  it('sets sort field and order', () => {
    const { sort, setSort } = useFilterSort(mockConfig)
    setSort('status', 'asc')
    expect(sort.value).toEqual({ field: 'status', order: 'asc' })
  })

  it('resets sort to default', () => {
    const { sort, setSort, resetSort } = useFilterSort(mockConfig)
    setSort('status', 'asc')
    resetSort()
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
  })

  it('initializes column visibility from defaults', () => {
    const { visibleColumns } = useFilterSort(mockConfig)
    expect(visibleColumns.value).toContain('title')
    expect(visibleColumns.value).toContain('status')
    expect(visibleColumns.value).toContain('project')
    expect(visibleColumns.value).not.toContain('creator')
  })

  it('toggles column visibility', () => {
    const { visibleColumns, toggleColumn } = useFilterSort(mockConfig)
    toggleColumn('creator')
    expect(visibleColumns.value).toContain('creator')
    toggleColumn('creator')
    expect(visibleColumns.value).not.toContain('creator')
  })

  it('cannot hide alwaysVisible columns', () => {
    const { visibleColumns, toggleColumn } = useFilterSort(mockConfig)
    toggleColumn('title')
    expect(visibleColumns.value).toContain('title')
  })

  it('computes apiParams from filters and sort', () => {
    const { apiParams, addFilter, setSort } = useFilterSort(mockConfig)
    addFilter('status', ['open', 'closed'])
    setSort('status', 'asc')
    expect(apiParams.value.status).toBe('open,closed')
    expect(apiParams.value.sort_by).toBe('status')
    expect(apiParams.value.sort_order).toBe('asc')
  })

  it('persists to and restores from localStorage', () => {
    const { addFilter, setSort, toggleColumn } = useFilterSort(mockConfig)
    addFilter('status', ['open'])
    setSort('status', 'asc')
    toggleColumn('creator')

    // Create a new instance — should restore from localStorage
    const { filters: f2, sort: s2, visibleColumns: v2 } = useFilterSort(mockConfig)
    expect(f2.value.status).toEqual(['open'])
    expect(s2.value).toEqual({ field: 'status', order: 'asc' })
    expect(v2.value).toContain('creator')
  })

  it('handles corrupted localStorage gracefully', () => {
    localStorage.setItem('codify:filters:test', 'not-valid-json')
    const { filters, sort } = useFilterSort(mockConfig)
    expect(filters.value).toEqual({})
    expect(sort.value).toEqual({ field: 'created_at', order: 'desc' })
  })

  it('omits default sort from apiParams', () => {
    const { apiParams } = useFilterSort(mockConfig)
    // Default sort should still be present for API clarity
    expect(apiParams.value.sort_by).toBe('created_at')
    expect(apiParams.value.sort_order).toBe('desc')
  })

  it('handles date-range filter in apiParams', () => {
    const configWithDate: FilterSortConfig = {
      ...mockConfig,
      filterFields: [
        ...mockConfig.filterFields,
        { key: 'created', label: 'Created', type: 'date-range', apiParam: 'created_after,created_before' } as FilterField,
      ],
    }
    const { apiParams, addFilter } = useFilterSort(configWithDate)
    addFilter('created', [1704067200000, 1704153600000])
    expect(apiParams.value.created_after).toBeDefined()
    expect(apiParams.value.created_before).toBeDefined()
  })
})
