import { describe, it, expect, vi, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import type { SortField } from '../../composables/useFilterSort'

const { mockT } = vi.hoisted(() => {
  const mockT = vi.fn((key: string) => key)
  return { mockT }
})

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: mockT,
    locale: { value: 'en' }
  })
}))

vi.mock('naive-ui', () => ({
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'size'],
    emits: ['update:value'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        value: props.value,
        onChange: (e: any) => emit('update:value', e.target?.value ?? '')
      }, (props.options || []).map((opt: any) =>
        h('option', { key: opt.value, value: opt.value }, opt.label)
      ))
    }
  }
}))

import SortPopover from './SortPopover.vue'

const defaultFields: SortField[] = [
  { key: 'created_at', label: 'filter.created' },
  { key: 'updated_at', label: 'filter.updated' },
  { key: 'name', label: 'filter.name' }
]

const mountComponent = (props: Partial<{ fields: SortField[]; sort: { field: string; order: 'asc' | 'desc' } }> = {}) =>
  mount(SortPopover, {
    props: {
      fields: defaultFields,
      sort: { field: 'created_at', order: 'desc' },
      ...props
    }
  })

describe('SortPopover', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('renders header with correct i18n key', () => {
    const wrapper = mountComponent()
    const header = wrapper.find('.sort-popover__header')
    expect(header.exists()).toBe(true)
    expect(header.text()).toBe('filter.ordering')
  })

  it('renders sort field selector section', () => {
    const wrapper = mountComponent()
    const sections = wrapper.findAll('.sort-popover__section')
    expect(sections.length).toBeGreaterThanOrEqual(1)
    const firstLabel = sections[0].find('.sort-popover__label')
    expect(firstLabel.exists()).toBe(true)
    expect(firstLabel.text()).toBe('filter.sortBy')
  })

  it('renders direction toggle section', () => {
    const wrapper = mountComponent()
    const sections = wrapper.findAll('.sort-popover__section')
    expect(sections.length).toBeGreaterThanOrEqual(2)
    const toggle = sections[1].find('.sort-popover__direction-toggle')
    expect(toggle.exists()).toBe(true)
  })

  it('renders all sort field options in the select', () => {
    const wrapper = mountComponent()
    const options = wrapper.findAll('.n-select option')
    expect(options.length).toBe(3)
  })

  it('fieldOptions computed maps fields correctly', () => {
    const wrapper = mountComponent()
    const vm = wrapper.vm as any
    expect(vm.fieldOptions).toEqual([
      { label: 'filter.created', value: 'created_at' },
      { label: 'filter.updated', value: 'updated_at' },
      { label: 'filter.name', value: 'name' }
    ])
  })

  it('direction toggle shows ascending when sort.order is asc', () => {
    const wrapper = mountComponent({ sort: { field: 'created_at', order: 'asc' } })
    const icon = wrapper.find('.sort-popover__direction-icon')
    expect(icon.text()).toBe('↑')
    const toggle = wrapper.find('.sort-popover__direction-toggle')
    expect(toggle.text()).toContain('filter.ascending')
  })

  it('direction toggle shows descending when sort.order is desc', () => {
    const wrapper = mountComponent({ sort: { field: 'created_at', order: 'desc' } })
    const icon = wrapper.find('.sort-popover__direction-icon')
    expect(icon.text()).toBe('↓')
    const toggle = wrapper.find('.sort-popover__direction-toggle')
    expect(toggle.text()).toContain('filter.descending')
  })

  it('clicking direction toggle emits setSort with toggled order (asc → desc)', async () => {
    const wrapper = mountComponent({ sort: { field: 'created_at', order: 'asc' } })
    await wrapper.find('.sort-popover__direction-toggle').trigger('click')
    const emitted = wrapper.emitted('setSort') as any[][]
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual(['created_at', 'desc'])
  })

  it('clicking direction toggle emits setSort with toggled order (desc → asc)', async () => {
    const wrapper = mountComponent({ sort: { field: 'created_at', order: 'desc' } })
    await wrapper.find('.sort-popover__direction-toggle').trigger('click')
    const emitted = wrapper.emitted('setSort') as any[][]
    expect(emitted).toHaveLength(1)
    expect(emitted[0]).toEqual(['created_at', 'asc'])
  })

  it('reset button emits resetSort', async () => {
    const wrapper = mountComponent()
    await wrapper.find('.sort-popover__reset').trigger('click')
    expect(wrapper.emitted('resetSort')).toHaveLength(1)
  })

  it('select passes current sort.field as value', () => {
    const wrapper = mountComponent({ sort: { field: 'updated_at', order: 'asc' } })
    const select = wrapper.find('.n-select')
    expect(select.attributes('value')).toBe('updated_at')
  })
})
