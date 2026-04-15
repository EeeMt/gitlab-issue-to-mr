import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import FilterToolbar from './FilterToolbar.vue'
import type { FilterSortConfig } from '../../composables/useFilterSort'

// ---------------------------------------------------------------------------
// Shared mock objects
// ---------------------------------------------------------------------------
const mocks = vi.hoisted(() => ({
  t: (key: string) => key
}))

// ---------------------------------------------------------------------------
// Module mocks
// ---------------------------------------------------------------------------
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: mocks.t, locale: { value: 'en' } })
}))

vi.mock('naive-ui', () => ({
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'size', 'clearable'],
    emits: ['update:value'],
    setup(props: any, { slots, emit }: any) {
      return () => h('div', { class: 'n-input', 'data-testid': 'filter-toolbar-search' }, [
        slots.prefix?.(),
        h('input', {
          value: props.value,
          placeholder: props.placeholder,
          onInput: (e: any) => emit('update:value', e.target?.value ?? '')
        })
      ])
    }
  },
  NButton: {
    name: 'NButton',
    props: ['size', 'secondary', 'type'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        'data-type': props.type,
        onClick: () => emit('click')
      }, [slots.icon?.(), slots.default?.()])
    }
  },
  NIcon: {
    name: 'NIcon',
    props: ['size'],
    setup(_p: any, { slots }: any) { return () => h('span', { class: 'n-icon' }, slots.default?.()) }
  },
  NPopover: {
    name: 'NPopover',
    props: ['trigger', 'placement', 'showArrow', 'raw'],
    setup(_p: any, { slots }: any) {
      return () => h('div', { class: 'n-popover' }, [slots.trigger?.(), slots.default?.()])
    }
  },
  NTag: {
    name: 'NTag',
    props: ['type', 'size', 'round', 'closable'],
    emits: ['close'],
    setup(props: any, { slots, emit }: any) {
      return () => h('span', {
        class: 'n-tag',
        onClick: () => {},
      }, [
        slots.default?.(),
        props.closable ? h('span', { class: 'n-tag__close', onClick: () => emit('close') }) : null
      ])
    }
  }
}))

vi.mock('./FilterPopover.vue', () => ({
  default: { name: 'FilterPopover', template: '<div class="filter-popover-stub" />' }
}))

vi.mock('./SortPopover.vue', () => ({
  default: { name: 'SortPopover', template: '<div class="sort-popover-stub" />' }
}))

vi.mock('./ColumnsPopover.vue', () => ({
  default: { name: 'ColumnsPopover', template: '<div class="columns-popover-stub" />' }
}))

vi.mock('@vicons/ionicons5', () => ({
  SearchOutline: { name: 'SearchOutline', render: () => h('span', 'search-icon') },
  FunnelOutline: { name: 'FunnelOutline', render: () => h('span', 'funnel-icon') },
  SwapVerticalOutline: { name: 'SwapVerticalOutline', render: () => h('span', 'swap-icon') },
  SettingsOutline: { name: 'SettingsOutline', render: () => h('span', 'settings-icon') }
}))

// ---------------------------------------------------------------------------
// Test data & helpers
// ---------------------------------------------------------------------------
const mockConfig: FilterSortConfig = {
  storageKey: 'test:filters',
  filterFields: [
    {
      key: 'status',
      label: 'filter.status',
      type: 'multi-select',
      options: () => [
        { label: 'Open', value: 'open' },
        { label: 'Closed', value: 'closed' },
        { label: 'In Progress', value: 'in_progress' }
      ]
    },
    {
      key: 'project',
      label: 'filter.project',
      type: 'single-select',
      options: () => [
        { label: 'Alpha', value: 1 },
        { label: 'Beta', value: 2 }
      ]
    },
    {
      key: 'created',
      label: 'filter.created',
      type: 'date-range'
    }
  ],
  sortFields: [
    { key: 'created_at', label: 'filter.createdAt' },
    { key: 'updated_at', label: 'filter.updatedAt' }
  ],
  columns: [
    { key: 'title', label: 'col.title', defaultVisible: true, alwaysVisible: true },
    { key: 'status', label: 'col.status', defaultVisible: true }
  ],
  defaultSort: { field: 'created_at', order: 'desc' }
}

const mountComponent = (overrides: Record<string, any> = {}) =>
  mount(FilterToolbar, {
    props: {
      config: mockConfig,
      filters: {},
      sort: { field: 'created_at', order: 'desc' },
      visibleColumns: ['title', 'status'],
      activeFilterCount: 0,
      hasActiveFilters: false,
      ...overrides
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('FilterToolbar', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  // 1
  it('renders search input', () => {
    wrapper = mountComponent()
    expect(wrapper.find('.n-input').exists()).toBe(true)
  })

  // 2
  it('renders filter, sort, columns buttons', () => {
    wrapper = mountComponent()
    const buttons = wrapper.findAll('.n-button')
    expect(buttons.length).toBeGreaterThanOrEqual(3)
  })

  // 3
  it('shows result count when provided', () => {
    wrapper = mountComponent({ resultCount: 42 })
    const count = wrapper.find('.filter-toolbar__count')
    expect(count.exists()).toBe(true)
    expect(count.text()).toContain('filter.resultCount')
  })

  // 4
  it('does NOT show result count when not provided', () => {
    wrapper = mountComponent()
    expect(wrapper.find('.filter-toolbar__count').exists()).toBe(false)
  })

  // 5
  it('shows filter chips when hasActiveFilters is true', () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { status: ['open'] },
      activeFilterCount: 1
    })
    expect(wrapper.find('.filter-toolbar__chips').exists()).toBe(true)
  })

  // 6
  it('does NOT show chips row when hasActiveFilters is false', () => {
    wrapper = mountComponent({ hasActiveFilters: false })
    expect(wrapper.find('.filter-toolbar__chips').exists()).toBe(false)
  })

  // 7
  it('clear all button emits clearAllFilters', async () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { status: ['open'] },
      activeFilterCount: 1
    })
    await wrapper.find('.filter-toolbar__clear-all').trigger('click')
    expect(wrapper.emitted('clearAllFilters')).toBeTruthy()
    expect(wrapper.emitted('clearAllFilters')).toHaveLength(1)
  })

  // 8
  it('chip close emits removeFilter with correct key', async () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { status: ['open'] },
      activeFilterCount: 1
    })
    const tagComponents = wrapper.findAllComponents({ name: 'NTag' })
    expect(tagComponents.length).toBeGreaterThanOrEqual(1)
    tagComponents[0].vm.$emit('close')
    await nextTick()
    expect(wrapper.emitted('removeFilter')).toBeTruthy()
    expect(wrapper.emitted('removeFilter')![0]).toEqual(['status'])
  })

  // 9
  it('search input debounces and emits search event', async () => {
    vi.useFakeTimers()
    wrapper = mountComponent()
    const vm = wrapper.vm as any
    vm.onSearchInput('hello')
    await nextTick()

    // Before debounce fires, no search event
    expect(wrapper.emitted('search')).toBeFalsy()

    vi.advanceTimersByTime(300)
    await nextTick()

    expect(wrapper.emitted('search')).toBeTruthy()
    expect(wrapper.emitted('search')![0]).toEqual(['hello'])
    vi.useRealTimers()
  })

  // 10
  it('sort label shows current sort field and direction arrow (desc)', () => {
    wrapper = mountComponent({ sort: { field: 'created_at', order: 'desc' } })
    const label = wrapper.find('.filter-toolbar__sort-label')
    expect(label.exists()).toBe(true)
    expect(label.text()).toContain('filter.createdAt')
    expect(label.text()).toContain('↓')
  })

  // 11
  it('sort label shows current sort field and direction arrow (asc)', () => {
    wrapper = mountComponent({ sort: { field: 'created_at', order: 'asc' } })
    const label = wrapper.find('.filter-toolbar__sort-label')
    expect(label.exists()).toBe(true)
    expect(label.text()).toContain('filter.createdAt')
    expect(label.text()).toContain('↑')
  })

  // 12
  it('filter chips display correct label for multi-select', () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { status: ['open', 'closed'] },
      activeFilterCount: 1
    })
    const tags = wrapper.findAll('.n-tag')
    expect(tags.length).toBeGreaterThanOrEqual(1)
    const chipText = tags[0].text()
    expect(chipText).toContain('filter.status')
    expect(chipText).toContain('Open')
    expect(chipText).toContain('Closed')
  })

  // 13
  it('filter chips display correct label for single-select', () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { project: 1 },
      activeFilterCount: 1
    })
    const tags = wrapper.findAll('.n-tag')
    expect(tags.length).toBeGreaterThanOrEqual(1)
    const chipText = tags[0].text()
    expect(chipText).toContain('filter.project')
    expect(chipText).toContain('Alpha')
  })

  // 14
  it('filter chips display correct label for date-range', () => {
    const ts1 = new Date('2024-01-15').getTime()
    const ts2 = new Date('2024-02-20').getTime()
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { created: [ts1, ts2] },
      activeFilterCount: 1
    })
    const tags = wrapper.findAll('.n-tag')
    expect(tags.length).toBeGreaterThanOrEqual(1)
    const chipText = tags[0].text()
    expect(chipText).toContain('filter.created')
    const fmt1 = new Date(ts1).toLocaleDateString()
    const fmt2 = new Date(ts2).toLocaleDateString()
    expect(chipText).toContain(fmt1)
    expect(chipText).toContain(fmt2)
  })

  // 15
  it('filter chips fall back to String(value) for unknown values', () => {
    wrapper = mountComponent({
      hasActiveFilters: true,
      filters: { status: ['unknown_val'] },
      activeFilterCount: 1
    })
    const tags = wrapper.findAll('.n-tag')
    expect(tags.length).toBeGreaterThanOrEqual(1)
    const chipText = tags[0].text()
    expect(chipText).toContain('filter.status')
    expect(chipText).toContain('unknown_val')
  })
})
