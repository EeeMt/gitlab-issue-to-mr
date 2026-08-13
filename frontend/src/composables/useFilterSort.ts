import { ref, computed, type Ref, type ComputedRef, type Component } from 'vue'

export interface FilterField {
  key: string
  label: string
  icon?: Component
  type: 'multi-select' | 'single-select' | 'date-range'
  options?: () => {
    label: string
    value: any
    color?: string
    count?: number
    truncateLabel?: boolean
  }[]
  optionsLoading?: () => boolean
  optionsError?: () => boolean
  optionsRetry?: () => void | Promise<void>
  searchable?: boolean
  apiParam?: string
  parseValue?: (value: string) => any
}

export interface SortField {
  key: string
  label: string
}

export interface ColumnDef {
  key: string
  label: string
  defaultVisible: boolean
  alwaysVisible?: boolean
}

export interface FilterSortConfig {
  storageKey: string
  filterFields: FilterField[]
  sortFields: SortField[]
  columns: ColumnDef[]
  defaultSort: { field: string; order: 'asc' | 'desc' }
  persistence?: {
    filters?: boolean
    sort?: boolean
    columns?: boolean
  }
}

interface PersistedState {
  filters?: Record<string, any>
  sort?: { field: string; order: 'asc' | 'desc' }
  visibleColumns?: string[]
}

function loadFromStorage(key: string): PersistedState | null {
  try {
    const raw = localStorage.getItem(key)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (parsed && typeof parsed === 'object') {
      return parsed as PersistedState
    }
    return null
  } catch {
    return null
  }
}

function saveToStorage(key: string, state: PersistedState) {
  try {
    localStorage.setItem(key, JSON.stringify(state))
  } catch (err) {
    console.warn('[useFilterSort] Failed to persist state:', err)
  }
}

/**
 * @param config - Filter/sort/column configuration
 * @param initialFilters - Optional seed values that take precedence over localStorage.
 *   Use this for URL query params so they win over persisted state on first load.
 * @param initialSort - Optional URL-owned sort state that takes precedence over localStorage.
 */
export function useFilterSort(
  config: FilterSortConfig,
  initialFilters?: Record<string, any>,
  initialSort?: { field: string; order: 'asc' | 'desc' },
) {
  const saved = loadFromStorage(config.storageKey)
  const persistFilters = config.persistence?.filters ?? true
  const persistSort = config.persistence?.sort ?? true
  const persistColumns = config.persistence?.columns ?? true

  const filters: Ref<Record<string, any>> = ref({
    ...(persistFilters ? saved?.filters ?? {} : {}),
    ...(initialFilters ?? {}),
  })
  const sort: Ref<{ field: string; order: 'asc' | 'desc' }> = ref(
    initialSort ?? (persistSort ? saved?.sort : undefined) ?? { ...config.defaultSort }
  )

  const defaultVisibleColumns = config.columns
    .filter((c) => c.defaultVisible)
    .map((c) => c.key)
  const visibleColumns: Ref<string[]> = ref(
    (persistColumns ? saved?.visibleColumns : undefined) ?? [...defaultVisibleColumns]
  )

  function persist() {
    const state: PersistedState = {}
    if (persistFilters) state.filters = filters.value
    if (persistSort) state.sort = sort.value
    if (persistColumns) state.visibleColumns = visibleColumns.value
    saveToStorage(config.storageKey, state)
  }

  function addFilter(key: string, value: any) {
    filters.value = { ...filters.value, [key]: value }
    persist()
  }

  function removeFilter(key: string) {
    const next = { ...filters.value }
    delete next[key]
    filters.value = next
    persist()
  }

  function clearAllFilters() {
    filters.value = {}
    persist()
  }

  function setSort(field: string, order: 'asc' | 'desc') {
    sort.value = { field, order }
    persist()
  }

  function resetSort() {
    sort.value = { ...config.defaultSort }
    persist()
  }

  function toggleColumn(key: string) {
    const col = config.columns.find((c) => c.key === key)
    if (col?.alwaysVisible) return
    const current = visibleColumns.value
    if (current.includes(key)) {
      visibleColumns.value = current.filter((k) => k !== key)
    } else {
      visibleColumns.value = [...current, key]
    }
    persist()
  }

  function resetColumns() {
    visibleColumns.value = [...defaultVisibleColumns]
    persist()
  }

  const activeFilterCount: ComputedRef<number> = computed(() => {
    return Object.keys(filters.value).length
  })

  const hasActiveFilters: ComputedRef<boolean> = computed(() => {
    return activeFilterCount.value > 0
  })

  const apiParams: ComputedRef<Record<string, string>> = computed(() => {
    const params: Record<string, string> = {}

    // Filters
    for (const field of config.filterFields) {
      const val = filters.value[field.key]
      if (val === undefined || val === null) continue

      if (field.type === 'date-range' && field.apiParam) {
        const [afterKey, beforeKey] = field.apiParam.split(',').map((s) => s.trim())
        if (Array.isArray(val) && val.length === 2) {
          if (val[0] !== null && val[0] !== undefined) {
            params[afterKey] = new Date(val[0]).toISOString()
          }
          if (val[1] !== null && val[1] !== undefined) {
            const endOfDay = new Date(val[1])
            endOfDay.setHours(23, 59, 59, 999)
            params[beforeKey] = endOfDay.toISOString()
          }
        }
      } else if (field.type === 'multi-select' && Array.isArray(val)) {
        if (val.length > 0) {
          params[field.apiParam ?? field.key] = val.join(',')
        }
      } else {
        params[field.apiParam ?? field.key] = String(val)
      }
    }

    // Sort
    params.sort_by = sort.value.field
    params.sort_order = sort.value.order

    return params
  })

  return {
    filters,
    sort,
    visibleColumns,
    apiParams,
    addFilter,
    removeFilter,
    clearAllFilters,
    setSort,
    resetSort,
    toggleColumn,
    resetColumns,
    activeFilterCount,
    hasActiveFilters,
  }
}
