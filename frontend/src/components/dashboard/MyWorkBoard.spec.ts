import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import MyWorkBoard, { type BoardColumn } from './MyWorkBoard.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: vi.fn((key: string) => key),
  }),
}))

vi.mock('naive-ui', () => ({
  NCard: {
    name: 'NCard',
    props: ['bordered'],
    setup(_props: unknown, { slots }: any) {
      return () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()])
    },
  },
  NIcon: {
    name: 'NIcon',
    props: ['size'],
    setup(_props: unknown, { slots }: any) {
      return () => h('i', { class: 'n-icon' }, slots.default?.())
    },
  },
  NScrollbar: {
    name: 'NScrollbar',
    props: ['trigger'],
    setup(props: any, { attrs, slots }: any) {
      return () =>
        h(
          'div',
          {
            ...attrs,
            class: ['n-scrollbar', attrs.class],
            'data-trigger': props.trigger,
          },
          slots.default?.(),
        )
    },
  },
}))

const issueColumns: BoardColumn[] = [
  {
    status: 'open',
    label: 'Open',
    count: 1,
    items: [
      {
        id: 1,
        title: '#1 Issue title',
        subtitle: 'Project',
        meta: ['P1'],
        route: '/issues/1',
      },
    ],
  },
  {
    status: 'closed',
    label: 'Closed',
    count: 0,
    items: [],
  },
]

const taskColumns: BoardColumn[] = [
  {
    status: 'running',
    label: 'Running',
    count: 1,
    items: [
      {
        id: 10,
        title: 'Task title',
        subtitle: 'Project',
        meta: ['P1'],
        route: '/tasks/10',
      },
    ],
  },
]

function mountBoard(isMobile = false) {
  return mount(MyWorkBoard, {
    props: {
      issueColumns,
      taskColumns,
      issueTotal: 1,
      taskTotal: 1,
      visibleLimit: 100,
      isMobile,
    },
  })
}

describe('MyWorkBoard', () => {
  it('uses one Naive UI scrollbar per lane body', () => {
    const wrapper = mountBoard()

    const laneScrollbars = wrapper.findAll('.my-work-board__column-body-scrollbar')
    const laneBodies = wrapper.findAll('.my-work-board__column-body')

    expect(wrapper.find('.my-work-board__columns-scrollbar').exists()).toBe(false)
    expect(laneScrollbars).toHaveLength(issueColumns.length)
    expect(laneBodies).toHaveLength(issueColumns.length)
    laneScrollbars.forEach((scrollbar) => {
      expect(scrollbar.classes()).toContain('n-scrollbar')
      expect(scrollbar.attributes('data-trigger')).toBe('hover')
    })
    laneBodies.forEach((laneBody) => {
      expect(laneBody.element.parentElement?.classList.contains('my-work-board__column-body-scrollbar')).toBe(true)
    })
  })

  it('keeps mobile lanes as separate Naive UI scrollbars', () => {
    const wrapper = mountBoard(true)

    const laneScrollbars = wrapper.findAll('.my-work-board__column-body-scrollbar')

    expect(wrapper.find('.my-work-board__columns-scrollbar--mobile').exists()).toBe(false)
    expect(wrapper.find('.my-work-board__columns--mobile').exists()).toBe(true)
    expect(laneScrollbars).toHaveLength(issueColumns.length)
    laneScrollbars.forEach((scrollbar) => {
      expect(scrollbar.classes()).toContain('n-scrollbar')
      expect(scrollbar.attributes('data-trigger')).toBe('hover')
    })
  })
})
