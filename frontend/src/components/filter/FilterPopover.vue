<template>
  <div class="filter-popover">
    <transition name="filter-slide" mode="out-in">
      <!-- Step 1: Category List -->
      <div v-if="!selectedCategory" key="categories" class="filter-popover__categories">
        <div class="filter-popover__header">{{ t('filter.filter') }}</div>
        <div
          v-for="field in fields"
          :key="field.key"
          class="filter-popover__item"
          :class="{ 'filter-popover__item--active': hasFilter(field.key) }"
          @click="selectCategory(field)"
        >
          <n-icon v-if="field.icon" size="16" class="filter-popover__item-icon">
            <component :is="field.icon" />
          </n-icon>
          <span class="filter-popover__item-label">{{ t(field.label) }}</span>
          <span v-if="hasFilter(field.key)" class="filter-popover__item-dot" />
          <span class="filter-popover__item-arrow">›</span>
        </div>
      </div>

      <!-- Step 2: Options Panel -->
      <div v-else key="options" class="filter-popover__options">
        <div class="filter-popover__options-header">
          <span class="filter-popover__back" @click="selectedCategory = null">← {{ t('filter.back') }}</span>
          <span class="filter-popover__options-title">{{ t(selectedCategory.label) }}</span>
        </div>

        <!-- Multi-select: checkboxes -->
        <template v-if="selectedCategory.type === 'multi-select'">
          <n-checkbox-group v-model:value="tempMultiValue" class="filter-popover__checkbox-group">
            <div
              v-for="opt in categoryOptions"
              :key="opt.value"
              class="filter-popover__option-row"
            >
              <n-checkbox :value="opt.value" :label="opt.label">
                <template #default>
                  <div class="filter-popover__option-content">
                    <span v-if="opt.color" class="filter-popover__color-dot" :style="{ background: opt.color }" />
                    <span>{{ opt.label }}</span>
                  </div>
                </template>
              </n-checkbox>
              <span v-if="opt.count !== undefined" class="filter-popover__count">{{ opt.count }}</span>
            </div>
          </n-checkbox-group>
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
            <span class="filter-popover__footer-action filter-popover__footer-action--primary" @click="applyMulti">{{ t('filter.apply') }}</span>
          </div>
        </template>

        <!-- Single-select: radio-style list -->
        <template v-else-if="selectedCategory.type === 'single-select'">
          <n-input
            v-if="categoryOptions.length > 6"
            v-model:value="optionSearch"
            :placeholder="t('filter.search')"
            size="small"
            clearable
            class="filter-popover__search"
          />
          <div
            v-for="opt in filteredOptions"
            :key="opt.value"
            class="filter-popover__option-row filter-popover__option-row--clickable"
            :class="{ 'filter-popover__option-row--selected': filters[selectedCategory.key] === opt.value }"
            @click="applySingle(opt.value)"
          >
            <span v-if="opt.color" class="filter-popover__color-dot" :style="{ background: opt.color }" />
            <span>{{ opt.label }}</span>
          </div>
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
          </div>
        </template>

        <!-- Date range -->
        <template v-else-if="selectedCategory.type === 'date-range'">
          <n-date-picker
            v-model:value="tempDateRange"
            type="daterange"
            clearable
            class="filter-popover__date-picker"
          />
          <div class="filter-popover__footer">
            <span class="filter-popover__footer-action" @click="clearCurrent">{{ t('filter.clear') }}</span>
            <span class="filter-popover__footer-action filter-popover__footer-action--primary" @click="applyDate">{{ t('filter.apply') }}</span>
          </div>
        </template>
      </div>
    </transition>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { NIcon, NCheckboxGroup, NCheckbox, NInput, NDatePicker } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { FilterField } from '../../composables/useFilterSort'

const props = defineProps<{
  fields: FilterField[]
  filters: Record<string, any>
}>()

const emit = defineEmits<{
  (e: 'addFilter', key: string, value: any): void
  (e: 'removeFilter', key: string): void
}>()

const { t } = useI18n()
const selectedCategory = ref<FilterField | null>(null)
const tempMultiValue = ref<any[]>([])
const tempDateRange = ref<[number, number] | null>(null)
const optionSearch = ref('')

function hasFilter(key: string): boolean {
  const val = props.filters[key]
  if (val === undefined || val === null) return false
  if (Array.isArray(val)) return val.length > 0
  return true
}

const categoryOptions = computed(() => {
  if (!selectedCategory.value?.options) return []
  return selectedCategory.value.options()
})

const filteredOptions = computed(() => {
  if (!optionSearch.value) return categoryOptions.value
  const q = optionSearch.value.toLowerCase()
  return categoryOptions.value.filter((o) => o.label.toLowerCase().includes(q))
})

function selectCategory(field: FilterField) {
  selectedCategory.value = field
  optionSearch.value = ''
  if (field.type === 'multi-select') {
    tempMultiValue.value = props.filters[field.key] ? [...props.filters[field.key]] : []
  } else if (field.type === 'date-range') {
    tempDateRange.value = props.filters[field.key] ?? null
  }
}

function applyMulti() {
  if (!selectedCategory.value) return
  if (tempMultiValue.value.length > 0) {
    emit('addFilter', selectedCategory.value.key, [...tempMultiValue.value])
  } else {
    emit('removeFilter', selectedCategory.value.key)
  }
  selectedCategory.value = null
}

function applySingle(value: any) {
  if (!selectedCategory.value) return
  emit('addFilter', selectedCategory.value.key, value)
  selectedCategory.value = null
}

function applyDate() {
  if (!selectedCategory.value) return
  if (tempDateRange.value) {
    emit('addFilter', selectedCategory.value.key, [...tempDateRange.value])
  } else {
    emit('removeFilter', selectedCategory.value.key)
  }
  selectedCategory.value = null
}

function clearCurrent() {
  if (!selectedCategory.value) return
  emit('removeFilter', selectedCategory.value.key)
  selectedCategory.value = null
}
</script>

<style scoped>
.filter-popover {
  width: 240px;
  max-height: 360px;
  overflow-y: auto;
  background: var(--n-color, #fff);
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06), 0 8px 24px rgba(0, 0, 0, 0.1);
  border: 1px solid var(--n-border-color, #e0e0e6);
  padding: 4px 0;
}
.filter-popover__header {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  color: var(--n-text-color-3, #888);
  padding: 8px 12px 4px;
}
.filter-popover__item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  cursor: pointer;
  border-radius: 4px;
  margin: 0 4px;
  transition: background 0.15s;
}
.filter-popover__item:hover {
  background: var(--n-color-hover, rgba(255,255,255,0.06));
}
.filter-popover__item--active {
  color: var(--n-primary-color, #4080ff);
}
.filter-popover__item-icon {
  flex-shrink: 0;
}
.filter-popover__item-label {
  flex: 1;
}
.filter-popover__item-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--n-primary-color, #4080ff);
}
.filter-popover__item-arrow {
  color: var(--n-text-color-3, #888);
  font-size: 14px;
}
.filter-popover__options-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--n-divider-color, #efeff5);
  margin: 0 8px 4px;
  padding-left: 4px;
  padding-right: 4px;
}
.filter-popover__back {
  color: var(--n-primary-color, #4080ff);
  cursor: pointer;
  font-size: 13px;
}
.filter-popover__options-title {
  font-weight: 600;
  font-size: 13px;
}
.filter-popover__checkbox-group {
  display: flex;
  flex-direction: column;
  padding: 0 8px;
}
.filter-popover__option-row {
  display: flex;
  align-items: center;
  padding: 6px 12px;
  gap: 8px;
}
.filter-popover__option-row--clickable {
  cursor: pointer;
  border-radius: 4px;
  margin: 0 4px;
}
.filter-popover__option-row--clickable:hover {
  background: var(--n-color-hover, rgba(255,255,255,0.06));
}
.filter-popover__option-row--selected {
  color: var(--n-primary-color, #4080ff);
  font-weight: 500;
}
.filter-popover__option-content {
  display: flex;
  align-items: center;
  gap: 6px;
}
.filter-popover__color-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}
.filter-popover__count {
  margin-left: auto;
  font-size: 12px;
  color: var(--n-text-color-3, #888);
}
.filter-popover__search {
  margin: 4px 8px 8px;
}
.filter-popover__date-picker {
  margin: 8px;
}
.filter-popover__footer {
  display: flex;
  justify-content: space-between;
  padding: 8px 4px;
  border-top: 1px solid var(--n-divider-color, #efeff5);
  margin: 4px 8px 0;
}
.filter-popover__footer-action {
  font-size: 12px;
  color: var(--n-text-color-3, #888);
  cursor: pointer;
}
.filter-popover__footer-action--primary {
  color: var(--n-primary-color, #4080ff);
}
.filter-slide-enter-active,
.filter-slide-leave-active {
  transition: opacity 0.15s ease;
}
.filter-slide-enter-from,
.filter-slide-leave-to {
  opacity: 0;
}
</style>
