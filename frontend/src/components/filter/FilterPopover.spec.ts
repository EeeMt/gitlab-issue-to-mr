import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h, nextTick } from 'vue'
import FilterPopover from './FilterPopover.vue'
import type { FilterField } from '../../composables/useFilterSort'

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
  NSpin: {
    name: 'NSpin',
    setup() {
      return () => h('span', { class: 'n-spin' })
    }
  },
  NButton: {
    name: 'NButton',
    props: ['text', 'type', 'size'],
    emits: ['click'],
    setup(_props: any, { slots, emit, attrs }: any) {
      return () => h('button', {
        ...attrs,
        class: ['n-button', attrs.class],
        onClick: () => emit('click'),
      }, slots.default?.())
    }
  },
  NIcon: {
    name: 'NIcon',
    props: ['size', 'component'],
    setup(_p: any, { slots }: any) {
      return () => h('span', { class: 'n-icon' }, slots.default?.())
    }
  },
  NCheckboxGroup: {
    name: 'NCheckboxGroup',
    props: ['value'],
    emits: ['update:value'],
    setup(props: any, { slots, emit }: any) {
      return () => h('div', { class: 'n-checkbox-group' }, slots.default?.())
    }
  },
  NCheckbox: {
    name: 'NCheckbox',
    props: ['value'],
    setup(props: any, { slots }: any) {
      return () =>
        h('div', { class: 'n-checkbox', 'data-value': props.value }, [
          slots.default?.()
        ])
    }
  },
  NInput: {
    name: 'NInput',
    props: ['value', 'placeholder', 'size', 'clearable'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h('input', {
          class: 'n-input',
          value: props.value,
          placeholder: props.placeholder,
          onInput: (e: any) => emit('update:value', e.target?.value ?? '')
        })
    }
  },
  NDatePicker: {
    name: 'NDatePicker',
    props: ['value', 'type', 'clearable'],
    emits: ['update:value'],
    setup(props: any) {
      return () => h('div', { class: 'n-date-picker' })
    }
  }
}))

// ---------------------------------------------------------------------------
// Test data & helpers
// ---------------------------------------------------------------------------
const multiSelectField: FilterField = {
  key: 'status',
  label: 'filter.status',
  type: 'multi-select',
  options: () => [
    { label: 'Open', value: 'open', color: '#18a058' },
    { label: 'Closed', value: 'closed', color: '#d03050' },
    { label: 'Running', value: 'running', count: 5 }
  ]
}

const singleSelectField: FilterField = {
  key: 'priority',
  label: 'filter.priority',
  type: 'single-select',
  options: () => [
    { label: 'P0', value: 0, color: '#d03050' },
    { label: 'P1', value: 1, color: '#f0a020' },
    { label: 'P2', value: 2, color: '#18a058' }
  ]
}

const dateRangeField: FilterField = {
  key: 'created',
  label: 'filter.created',
  type: 'date-range'
}

const defaultFields: FilterField[] = [multiSelectField, singleSelectField, dateRangeField]

const mountComponent = (
  props: Partial<{ fields: FilterField[]; filters: Record<string, any> }> = {}
) =>
  mount(FilterPopover, {
    props: {
      fields: defaultFields,
      filters: {},
      ...props
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('FilterPopover', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  // 1. Renders category list with all fields
  it('renders category list with all fields', () => {
    wrapper = mountComponent()
    const items = wrapper.findAll('.filter-popover__item')
    expect(items).toHaveLength(3)
    const labels = items.map((el) => el.find('.filter-popover__item-label').text())
    expect(labels).toEqual(['filter.status', 'filter.priority', 'filter.created'])
  })

  // 2. Shows active indicator dot for fields with filters
  it('shows active indicator dot for fields with filters', () => {
    wrapper = mountComponent({ filters: { status: ['open'] } })
    const items = wrapper.findAll('.filter-popover__item')

    // status item (index 0) should have the dot and active class
    expect(items[0].find('.filter-popover__item-dot').exists()).toBe(true)
    expect(items[0].classes()).toContain('filter-popover__item--active')

    // priority item (index 1) should NOT have dot
    expect(items[1].find('.filter-popover__item-dot').exists()).toBe(false)
    expect(items[1].classes()).not.toContain('filter-popover__item--active')
  })

  // 3. Clicking category opens options panel (multi-select)
  it('clicking category opens multi-select options panel', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__options').exists()).toBe(true)
    expect(wrapper.find('.filter-popover__categories').exists()).toBe(false)
    expect(wrapper.find('.n-checkbox-group').exists()).toBe(true)
  })

  it('truncates marked option labels and exposes the full label on hover', async () => {
    const longUsername = 'a-very-long-initiator-username-that-needs-truncation'
    wrapper = mountComponent({
      fields: [{
        key: 'initiator',
        label: 'filter.initiator',
        type: 'multi-select',
        options: () => [{ label: longUsername, value: 'user:1', truncateLabel: true }],
      }],
    })

    await wrapper.find('.filter-popover__item').trigger('click')
    await nextTick()

    const label = wrapper.find('.truncated-option-label')
    expect(label.text()).toBe(longUsername)
    expect(label.attributes('title')).toBe(longUsername)
  })

  // 4. Clicking category opens options panel (single-select)
  it('clicking category opens single-select options panel', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[1].trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__options').exists()).toBe(true)
    expect(wrapper.find('.filter-popover__categories').exists()).toBe(false)
    const optionRows = wrapper.findAll('.filter-popover__option-row--clickable')
    expect(optionRows).toHaveLength(3)
  })

  // 5. Clicking category opens options panel (date-range)
  it('clicking category opens date-range options panel', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__options').exists()).toBe(true)
    expect(wrapper.find('.filter-popover__categories').exists()).toBe(false)
    expect(wrapper.find('.filter-popover__date-picker').exists()).toBe(true)
  })

  // 6. Back button returns to category list
  it('back button returns to category list', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()
    expect(wrapper.find('.filter-popover__options').exists()).toBe(true)

    await wrapper.find('.filter-popover__back').trigger('click')
    await nextTick()
    expect(wrapper.find('.filter-popover__categories').exists()).toBe(true)
    expect(wrapper.find('.filter-popover__options').exists()).toBe(false)
  })

  // 7. Multi-select: applies selections, emits addFilter with array
  it('multi-select apply emits addFilter with array', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    vm.tempMultiValue = ['open', 'closed']
    await nextTick()

    const applyBtn = wrapper.findAll('.filter-popover__footer-action--primary')
    await applyBtn[0].trigger('click')

    const emitted = wrapper.emitted('addFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['status', ['open', 'closed']])
  })

  // 8. Multi-select: clearing emits removeFilter
  it('multi-select clear emits removeFilter', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    const clearBtn = wrapper.findAll('.filter-popover__footer-action').filter(
      (el) => !el.classes().includes('filter-popover__footer-action--primary')
    )
    await clearBtn[0].trigger('click')

    const emitted = wrapper.emitted('removeFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['status'])
  })

  // 9. Multi-select: empty selection emits removeFilter
  it('multi-select apply with empty selection emits removeFilter', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    vm.tempMultiValue = []
    await nextTick()

    const applyBtn = wrapper.findAll('.filter-popover__footer-action--primary')
    await applyBtn[0].trigger('click')

    const emitted = wrapper.emitted('removeFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['status'])
  })

  // 10. Single-select: clicking option emits addFilter with value
  it('single-select clicking option emits addFilter with value', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[1].trigger('click')
    await nextTick()

    const optionRows = wrapper.findAll('.filter-popover__option-row--clickable')
    await optionRows[1].trigger('click')

    const emitted = wrapper.emitted('addFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['priority', 1])
  })

  // 11. Single-select: search input filters options (when > 6 options)
  it('single-select search input filters options when > 6 options', async () => {
    const manyOptionsField: FilterField = {
      key: 'project',
      label: 'filter.project',
      type: 'single-select',
      options: () => [
        { label: 'Alpha', value: 'alpha' },
        { label: 'Beta', value: 'beta' },
        { label: 'Gamma', value: 'gamma' },
        { label: 'Delta', value: 'delta' },
        { label: 'Epsilon', value: 'epsilon' },
        { label: 'Zeta', value: 'zeta' },
        { label: 'Theta', value: 'theta' }
      ]
    }

    wrapper = mountComponent({ fields: [manyOptionsField] })
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__search').exists()).toBe(true)
    let rows = wrapper.findAll('.filter-popover__option-row--clickable')
    expect(rows).toHaveLength(7)

    const vm = wrapper.vm as any
    vm.optionSearch = 'alp'
    await nextTick()

    rows = wrapper.findAll('.filter-popover__option-row--clickable')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('Alpha')
  })

  // 12. Single-select: search input hidden when <= 6 options
  it('single-select search input hidden when <= 6 options', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[1].trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__search').exists()).toBe(false)
  })

  it('searches explicitly searchable multi-select options', async () => {
    const searchableField: FilterField = {
      ...multiSelectField,
      searchable: true,
    }
    wrapper = mountComponent({ fields: [searchableField] })
    await wrapper.find('.filter-popover__item').trigger('click')
    await nextTick()

    expect(wrapper.find('.filter-popover__search').exists()).toBe(true)
    const vm = wrapper.vm as any
    vm.optionSearch = 'run'
    await nextTick()

    const rows = wrapper.findAll('.filter-popover__option-row')
    expect(rows).toHaveLength(1)
    expect(rows[0].text()).toContain('Running')
  })

  it('shows loading, error, and empty states for async multi-select options', async () => {
    const loadingField: FilterField = {
      ...multiSelectField,
      optionsLoading: () => true,
    }
    wrapper = mountComponent({ fields: [loadingField] })
    await wrapper.find('.filter-popover__item').trigger('click')
    await nextTick()
    expect(wrapper.find('.n-spin').exists()).toBe(true)
    wrapper.unmount()

    const errorField: FilterField = {
      ...multiSelectField,
      optionsError: () => true,
      optionsRetry: vi.fn(),
    }
    wrapper = mountComponent({ fields: [errorField] })
    await wrapper.find('.filter-popover__item').trigger('click')
    await nextTick()
    expect(wrapper.find('.filter-popover__state--error').text()).toContain('filter.loadFailed')
    await wrapper.find('.filter-popover__retry').trigger('click')
    expect(errorField.optionsRetry).toHaveBeenCalledTimes(1)
    wrapper.unmount()

    const emptyField: FilterField = {
      ...multiSelectField,
      options: () => [],
    }
    wrapper = mountComponent({ fields: [emptyField] })
    await wrapper.find('.filter-popover__item').trigger('click')
    await nextTick()
    expect(wrapper.find('.filter-popover__state').text()).toBe('filter.noResults')
  })

  // 13. Single-select: clear emits removeFilter
  it('single-select clear emits removeFilter', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[1].trigger('click')
    await nextTick()

    await wrapper.find('.filter-popover__footer-action').trigger('click')

    const emitted = wrapper.emitted('removeFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['priority'])
  })

  // 14. Date-range: apply emits addFilter with date tuple
  it('date-range apply emits addFilter with date tuple', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    const ts1 = 1700000000000
    const ts2 = 1700100000000
    vm.tempDateRange = [ts1, ts2]
    await nextTick()

    const applyBtn = wrapper.findAll('.filter-popover__footer-action--primary')
    await applyBtn[0].trigger('click')

    const emitted = wrapper.emitted('addFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['created', [ts1, ts2]])
  })

  // 15. Date-range: apply with null emits removeFilter
  it('date-range apply with null emits removeFilter', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    vm.tempDateRange = null
    await nextTick()

    const applyBtn = wrapper.findAll('.filter-popover__footer-action--primary')
    await applyBtn[0].trigger('click')

    const emitted = wrapper.emitted('removeFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['created'])
  })

  // 16. Date-range: clear emits removeFilter
  it('date-range clear emits removeFilter', async () => {
    wrapper = mountComponent()
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    const clearBtn = wrapper.findAll('.filter-popover__footer-action').filter(
      (el) => !el.classes().includes('filter-popover__footer-action--primary')
    )
    await clearBtn[0].trigger('click')

    const emitted = wrapper.emitted('removeFilter')
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual(['created'])
  })

  // 17. selectCategory initializes tempMultiValue from existing filters
  it('selectCategory initializes tempMultiValue from existing filters', async () => {
    wrapper = mountComponent({ filters: { status: ['open', 'running'] } })
    await wrapper.findAll('.filter-popover__item')[0].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    expect(vm.tempMultiValue).toEqual(['open', 'running'])
  })

  // 18. selectCategory initializes tempDateRange from existing filters
  it('selectCategory initializes tempDateRange from existing filters', async () => {
    const ts1 = 1700000000000
    const ts2 = 1700100000000
    wrapper = mountComponent({ filters: { created: [ts1, ts2] } })
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    const vm = wrapper.vm as any
    expect(vm.tempDateRange).toEqual([ts1, ts2])
  })

  it('does not pass a partial URL date range to the range picker', async () => {
    const ts = 1700000000000
    wrapper = mountComponent({ filters: { created: [ts, null] } })
    await wrapper.findAll('.filter-popover__item')[2].trigger('click')
    await nextTick()

    expect((wrapper.vm as any).tempDateRange).toBeNull()
  })

  // 19. hasFilter returns false for undefined/null/empty array values
  it('hasFilter returns false for undefined, null, and empty array', () => {
    wrapper = mountComponent({ filters: { status: [], priority: null } })
    const items = wrapper.findAll('.filter-popover__item')

    // status has empty array → no dot
    expect(items[0].find('.filter-popover__item-dot').exists()).toBe(false)
    expect(items[0].classes()).not.toContain('filter-popover__item--active')

    // priority has null → no dot
    expect(items[1].find('.filter-popover__item-dot').exists()).toBe(false)
    expect(items[1].classes()).not.toContain('filter-popover__item--active')

    // created is undefined → no dot
    expect(items[2].find('.filter-popover__item-dot').exists()).toBe(false)
    expect(items[2].classes()).not.toContain('filter-popover__item--active')
  })
})
