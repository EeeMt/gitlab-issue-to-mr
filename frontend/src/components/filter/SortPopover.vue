<template>
  <div class="sort-popover">
    <div class="sort-popover__header">{{ t('filter.ordering') }}</div>

    <div class="sort-popover__section">
      <div class="sort-popover__label">{{ t('filter.sortBy') }}</div>
      <n-select
        :value="sort.field"
        :options="fieldOptions"
        size="small"
        @update:value="(val: string) => emit('setSort', val, sort.order)"
      />
    </div>

    <div class="sort-popover__section">
      <div class="sort-popover__label">{{ t('filter.direction') }}</div>
      <n-button-group size="small" class="sort-popover__direction">
        <n-button
          :type="sort.order === 'asc' ? 'primary' : 'default'"
          :secondary="sort.order !== 'asc'"
          @click="emit('setSort', sort.field, 'asc')"
        >
          ↑ {{ t('filter.ascending') }}
        </n-button>
        <n-button
          :type="sort.order === 'desc' ? 'primary' : 'default'"
          :secondary="sort.order !== 'desc'"
          @click="emit('setSort', sort.field, 'desc')"
        >
          ↓ {{ t('filter.descending') }}
        </n-button>
      </n-button-group>
    </div>

    <div class="sort-popover__footer">
      <span class="sort-popover__reset" @click="emit('resetSort')">{{ t('filter.resetDefault') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSelect, NButtonGroup, NButton } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { SortField } from '../../composables/useFilterSort'

const props = defineProps<{
  fields: SortField[]
  sort: { field: string; order: 'asc' | 'desc' }
}>()

const emit = defineEmits<{
  (e: 'setSort', field: string, order: 'asc' | 'desc'): void
  (e: 'resetSort'): void
}>()

const { t } = useI18n()

const fieldOptions = computed(() =>
  props.fields.map((f) => ({ label: t(f.label), value: f.key }))
)
</script>

<style scoped>
.sort-popover {
  width: 240px;
  background: var(--n-color, #fff);
  border-radius: 12px;
  box-shadow: 0 3px 14px rgba(0, 0, 0, 0.12);
  border: 1px solid var(--n-border-color, #e0e0e6);
  padding: 4px 0;
}
.sort-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.sort-popover__section {
  padding: 8px 12px;
}
.sort-popover__label {
  font-size: 11px;
  color: var(--n-text-color-3, #888);
  margin-bottom: 4px;
}
.sort-popover__direction {
  width: 100%;
  display: flex;
}
.sort-popover__direction :deep(.n-button) {
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  padding: 0 6px;
  min-width: 0;
}
.sort-popover__footer {
  padding: 8px 4px;
  border-top: 1px solid var(--n-divider-color, #efeff5);
  margin: 0 8px;
}
.sort-popover__reset {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
</style>
