import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import ColumnsPopover from './ColumnsPopover.vue'
import type { ColumnDef } from '../../composables/useFilterSort'

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
  NSwitch: {
    name: 'NSwitch',
    props: ['value', 'size'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () =>
        h(
          'button',
          {
            class: 'n-switch',
            'data-checked': props.value ? 'true' : 'false',
            role: 'switch',
            onClick: () => emit('update:value', !props.value)
          },
          props.value ? 'ON' : 'OFF'
        )
    }
  }
}))

// ---------------------------------------------------------------------------
// Test data & helpers
// ---------------------------------------------------------------------------
const defaultColumns: ColumnDef[] = [
  { key: 'title', label: 'columns.title', defaultVisible: true, alwaysVisible: true },
  { key: 'status', label: 'columns.status', defaultVisible: true },
  { key: 'project', label: 'columns.project', defaultVisible: true },
  { key: 'creator', label: 'columns.creator', defaultVisible: false },
  { key: 'date', label: 'columns.date', defaultVisible: true }
]

const mountComponent = (
  props: Partial<{ columns: ColumnDef[]; visibleColumns: string[] }> = {}
) =>
  mount(ColumnsPopover, {
    props: {
      columns: defaultColumns,
      visibleColumns: ['status', 'project', 'date'],
      ...props
    }
  })

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------
describe('ColumnsPopover', () => {
  let wrapper: ReturnType<typeof mount> | null = null

  afterEach(() => {
    if (wrapper) {
      wrapper.unmount()
      wrapper = null
    }
  })

  // 1
  it('renders header with correct i18n key', () => {
    wrapper = mountComponent()
    const header = wrapper.find('.columns-popover__header')
    expect(header.exists()).toBe(true)
    expect(header.text()).toBe('filter.columns')
  })

  // 2
  it('renders only toggleable columns (filters out alwaysVisible)', () => {
    wrapper = mountComponent()
    const rows = wrapper.findAll('.columns-popover__row')
    expect(rows).toHaveLength(4)
  })

  // 3
  it('does NOT render alwaysVisible columns', () => {
    wrapper = mountComponent()
    const labels = wrapper
      .findAll('.columns-popover__label')
      .map((el) => el.text())
    expect(labels).not.toContain('columns.title')
  })

  // 4
  it('shows label for each toggleable column', () => {
    wrapper = mountComponent()
    const labels = wrapper
      .findAll('.columns-popover__label')
      .map((el) => el.text())
    expect(labels).toEqual([
      'columns.status',
      'columns.project',
      'columns.creator',
      'columns.date'
    ])
  })

  // 5
  it('switch value reflects visibleColumns — visible column has data-checked true', () => {
    wrapper = mountComponent()
    const switches = wrapper.findAll('.n-switch')
    // 'status' is index 0 and is in visibleColumns
    expect(switches[0].attributes('data-checked')).toBe('true')
  })

  // 6
  it('switch value reflects visibleColumns — hidden column has data-checked false', () => {
    wrapper = mountComponent()
    const switches = wrapper.findAll('.n-switch')
    // 'creator' is index 2 and is NOT in visibleColumns
    expect(switches[2].attributes('data-checked')).toBe('false')
  })

  // 7
  it('clicking switch emits toggleColumn with correct column key', async () => {
    wrapper = mountComponent()
    const switches = wrapper.findAll('.n-switch')
    // Click the 'status' switch (index 0)
    await switches[0].trigger('click')
    expect(wrapper.emitted('toggleColumn')).toBeTruthy()
    expect(wrapper.emitted('toggleColumn')![0]).toEqual(['status'])
  })

  // 8
  it('clicking switch emits toggleColumn for each respective column', async () => {
    wrapper = mountComponent()
    const switches = wrapper.findAll('.n-switch')
    // Click 'project' (index 1) then 'creator' (index 2)
    await switches[1].trigger('click')
    await switches[2].trigger('click')
    const emitted = wrapper.emitted('toggleColumn')!
    expect(emitted).toHaveLength(2)
    expect(emitted[0]).toEqual(['project'])
    expect(emitted[1]).toEqual(['creator'])
  })

  // 9
  it('reset button emits resetColumns', async () => {
    wrapper = mountComponent()
    await wrapper.find('.columns-popover__reset').trigger('click')
    expect(wrapper.emitted('resetColumns')).toBeTruthy()
    expect(wrapper.emitted('resetColumns')).toHaveLength(1)
  })

  // 10
  it('toggleableColumns computed filters correctly', () => {
    wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.toggleableColumns).toHaveLength(4)
    const keys = vm.toggleableColumns.map((c: ColumnDef) => c.key)
    expect(keys).toEqual(['status', 'project', 'creator', 'date'])
  })

  // 11
  it('renders correctly with all columns toggleable (none alwaysVisible)', () => {
    const allToggleable: ColumnDef[] = [
      { key: 'a', label: 'col.a', defaultVisible: true },
      { key: 'b', label: 'col.b', defaultVisible: true },
      { key: 'c', label: 'col.c', defaultVisible: false }
    ]
    wrapper = mountComponent({ columns: allToggleable, visibleColumns: ['a', 'b'] })
    const rows = wrapper.findAll('.columns-popover__row')
    expect(rows).toHaveLength(3)
  })

  // 12
  it('renders correctly with empty columns array', () => {
    wrapper = mountComponent({ columns: [], visibleColumns: [] })
    const rows = wrapper.findAll('.columns-popover__row')
    expect(rows).toHaveLength(0)
  })
})
