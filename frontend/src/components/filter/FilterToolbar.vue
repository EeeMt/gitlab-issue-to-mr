<template>
  <div class="filter-toolbar" data-testid="filter-toolbar">
    <!-- Toolbar row -->
    <div class="filter-toolbar__row">
      <!-- Search -->
      <n-input
        :value="searchValue"
        :placeholder="searchPlaceholder || t('filter.search')"
        size="small"
        clearable
        class="filter-toolbar__search"
        data-testid="filter-toolbar-search"
        @update:value="onSearchInput"
      >
        <template #prefix>
          <n-icon size="16"><SearchOutline /></n-icon>
        </template>
      </n-input>

      <!-- Filter button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw :style="{ boxShadow: 'none' }">
        <template #trigger>
          <n-button size="small" :secondary="!hasActiveFilters" :type="hasActiveFilters ? 'primary' : 'default'" data-testid="filter-toolbar-filter-btn">
            <template #icon>
              <n-icon size="14"><FunnelOutline /></n-icon>
            </template>
            {{ t('filter.filter') }}
          </n-button>
        </template>
        <FilterPopover
          :fields="config.filterFields"
          :filters="filters"
          @add-filter="(key, val) => emit('addFilter', key, val)"
          @remove-filter="(key) => emit('removeFilter', key)"
        />
      </n-popover>

      <!-- Sort button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw :style="{ boxShadow: 'none' }">
        <template #trigger>
          <n-button size="small" secondary data-testid="filter-toolbar-sort-btn">
            <template #icon>
              <n-icon size="14"><SwapVerticalOutline /></n-icon>
            </template>
            {{ t('filter.sort') }}
            <span class="filter-toolbar__sort-label">{{ currentSortLabel }}</span>
          </n-button>
        </template>
        <SortPopover
          :fields="config.sortFields"
          :sort="sort"
          @set-sort="(field, order) => emit('setSort', field, order)"
          @reset-sort="emit('resetSort')"
        />
      </n-popover>

      <!-- Columns button -->
      <n-popover trigger="click" placement="bottom-start" :show-arrow="false" raw :style="{ boxShadow: 'none' }">
        <template #trigger>
          <n-button size="small" secondary data-testid="filter-toolbar-columns-btn">
            <template #icon>
              <n-icon size="14"><SettingsOutline /></n-icon>
            </template>
            {{ t('filter.columns') }}
          </n-button>
        </template>
        <ColumnsPopover
          :columns="config.columns"
          :visible-columns="visibleColumns"
          @toggle-column="(key) => emit('toggleColumn', key)"
          @reset-columns="emit('resetColumns')"
        />
      </n-popover>

      <div class="filter-toolbar__spacer" />

      <!-- Result count -->
      <span v-if="resultCount !== undefined" class="filter-toolbar__count" data-testid="filter-toolbar-count">
        {{ t('filter.resultCount', { count: resultCount }) }}
      </span>
    </div>

    <!-- Active filter chips row -->
    <div v-if="hasActiveFilters" class="filter-toolbar__chips" data-testid="filter-toolbar-chips">
      <n-tag
        v-for="chip in filterChips"
        :key="chip.key"
        :type="chip.type || 'info'"
        size="small"
        round
        closable
        @close="emit('removeFilter', chip.key)"
      >
        {{ chip.label }}
      </n-tag>
      <span class="filter-toolbar__clear-all" @click="emit('clearAllFilters')">
        {{ t('filter.clearAll') }}
      </span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NInput, NButton, NIcon, NPopover, NTag } from 'naive-ui'
import { SearchOutline, FunnelOutline, SwapVerticalOutline, SettingsOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { FilterSortConfig } from '../../composables/useFilterSort'
import FilterPopover from './FilterPopover.vue'
import SortPopover from './SortPopover.vue'
import ColumnsPopover from './ColumnsPopover.vue'

const props = defineProps<{
  config: FilterSortConfig
  filters: Record<string, any>
  sort: { field: string; order: 'asc' | 'desc' }
  visibleColumns: string[]
  activeFilterCount: number
  hasActiveFilters: boolean
  resultCount?: number
  searchPlaceholder?: string
}>()

const emit = defineEmits<{
  (e: 'addFilter', key: string, value: any): void
  (e: 'removeFilter', key: string): void
  (e: 'clearAllFilters'): void
  (e: 'setSort', field: string, order: 'asc' | 'desc'): void
  (e: 'resetSort'): void
  (e: 'toggleColumn', key: string): void
  (e: 'resetColumns'): void
  (e: 'search', term: string): void
}>()

const { t } = useI18n()
const searchValue = ref('')
let debounceTimer: ReturnType<typeof setTimeout> | null = null

function onSearchInput(val: string) {
  searchValue.value = val
  if (debounceTimer) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    emit('search', val)
  }, 300)
}

const currentSortLabel = computed(() => {
  const field = props.config.sortFields.find((f) => f.key === props.sort.field)
  const label = field ? t(field.label) : props.sort.field
  const arrow = props.sort.order === 'asc' ? '↑' : '↓'
  return `${label} ${arrow}`
})

const filterChips = computed(() => {
  const chips: { key: string; label: string; type?: 'info' | 'success' | 'warning' | 'error' }[] = []
  for (const field of props.config.filterFields) {
    const val = props.filters[field.key]
    if (val === undefined || val === null) continue
    if (Array.isArray(val) && val.length === 0) continue

    let displayValue: string
    if (field.type === 'multi-select' && Array.isArray(val)) {
      const opts = field.options?.() ?? []
      displayValue = val.map((v: any) => opts.find((o) => o.value === v)?.label ?? String(v)).join(', ')
    } else if (field.type === 'single-select') {
      const opts = field.options?.() ?? []
      displayValue = opts.find((o) => o.value === val)?.label ?? String(val)
    } else if (field.type === 'date-range' && Array.isArray(val)) {
      const fmt = (ts: number) => new Date(ts).toLocaleDateString()
      displayValue = `${fmt(val[0])} – ${fmt(val[1])}`
    } else {
      displayValue = String(val)
    }

    chips.push({ key: field.key, label: `${t(field.label)}: ${displayValue}` })
  }
  return chips
})
</script>

<style scoped>
.filter-toolbar {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.filter-toolbar__row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.filter-toolbar__search {
  width: 200px;
  flex-shrink: 0;
}
.filter-toolbar__sort-label {
  font-size: 11px;
  color: var(--n-text-color-3, #888);
  margin-left: 4px;
}
.filter-toolbar__spacer {
  flex: 1;
}
.filter-toolbar__count {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
}
.filter-toolbar__chips {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.filter-toolbar__clear-all {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
  margin-left: 4px;
}
.filter-toolbar__clear-all:hover {
  color: var(--n-text-color, #fff);
}
</style>
