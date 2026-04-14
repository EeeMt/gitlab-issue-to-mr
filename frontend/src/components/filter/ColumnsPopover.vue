<template>
  <div class="columns-popover">
    <div class="columns-popover__header">{{ t('filter.columns') }}</div>
    <div
      v-for="col in toggleableColumns"
      :key="col.key"
      class="columns-popover__row"
    >
      <span class="columns-popover__label">{{ t(col.label) }}</span>
      <n-switch
        :value="visibleColumns.includes(col.key)"
        size="small"
        @update:value="() => emit('toggleColumn', col.key)"
      />
    </div>
    <div class="columns-popover__footer">
      <span class="columns-popover__reset" @click="emit('resetColumns')">{{ t('filter.resetDefault') }}</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NSwitch } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { ColumnDef } from '../../composables/useFilterSort'

const props = defineProps<{
  columns: ColumnDef[]
  visibleColumns: string[]
}>()

const emit = defineEmits<{
  (e: 'toggleColumn', key: string): void
  (e: 'resetColumns'): void
}>()

const { t } = useI18n()

const toggleableColumns = computed(() =>
  props.columns.filter((c) => !c.alwaysVisible)
)
</script>

<style scoped>
.columns-popover {
  width: 220px;
}
.columns-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.columns-popover__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  border-bottom: 1px solid var(--n-border-color, rgba(255,255,255,0.06));
}
.columns-popover__label {
  font-size: 13px;
}
.columns-popover__footer {
  padding: 8px 12px;
  border-top: 1px solid var(--n-border-color, #333);
}
.columns-popover__reset {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
</style>
