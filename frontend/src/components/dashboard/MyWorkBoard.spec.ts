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
  NButton: {
    name: 'NButton',
    props: ['text', 'size'],
    setup(props: any, { attrs, slots }: any) {
      return () =>
        h(
          'button',
          {
            ...attrs,
            class: ['n-button', attrs.class],
            'data-text': props.text ? 'true' : undefined,
            'data-size': props.size,
          },
          slots.default?.(),
        )
    },
  },
  NScrollbar: {
    name: 'NScrollbar',
    props: ['trigger', 'xScrollable', 'contentStyle'],
    setup(props: any, { attrs, slots }: any) {
      return () =>
        h(
          'div',
          {
            ...attrs,
            class: ['n-scrollbar', attrs.class],
            'data-trigger': props.trigger,
            'data-x-scrollable': props.xScrollable ? 'true' : undefined,
          'data-content-style': props.contentStyle,
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
    const outerScrollbar = wrapper.find('.my-work-board__columns-scrollbar')

    // outer horizontal NScrollbar is present on desktop
    expect(outerScrollbar.exists()).toBe(true)
    expect(outerScrollbar.classes()).toContain('n-scrollbar')
    expect(outerScrollbar.attributes('data-x-scrollable')).toBe('true')
    expect(outerScrollbar.attributes('data-content-style')).toBe('height: 100%; padding-bottom: 8px;')
    expect(outerScrollbar.attributes('data-trigger')).toBe('hover')
    // per-lane scrollbars are still present
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
    const outerScrollbar = wrapper.find('.my-work-board__columns-scrollbar--mobile')

    // outer NScrollbar is present in mobile mode (not x-scrollable)
    expect(outerScrollbar.exists()).toBe(true)
    expect(outerScrollbar.classes()).toContain('n-scrollbar')
    expect(outerScrollbar.attributes('data-x-scrollable')).toBeUndefined()
    expect(outerScrollbar.attributes('data-content-style')).toBe('padding-bottom: 8px;')
    expect(wrapper.find('.my-work-board__columns--mobile').exists()).toBe(true)
    expect(laneScrollbars).toHaveLength(issueColumns.length)
    laneScrollbars.forEach((scrollbar) => {
      expect(scrollbar.classes()).toContain('n-scrollbar')
      expect(scrollbar.attributes('data-trigger')).toBe('hover')
    })
  })

  it('shows limit notice when total exceeds visibleLimit', async () => {
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns,
        issueTotal: 25,
        taskTotal: 1,
        visibleLimit: 20,
        isMobile: false,
      },
    })
    const notice = wrapper.find('[data-testid="my-work-board-notice-issues"]')
    expect(notice.exists()).toBe(true)
    expect(notice.text()).toContain('dashboard.myWorkBoard.limitNotice')
  })

  it('hides limit notice when total is within visibleLimit', () => {
    const wrapper = mountBoard() // issueTotal: 1, visibleLimit: 100
    expect(wrapper.find('[data-testid="my-work-board-notice-issues"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="my-work-board-notice-tasks"]').exists()).toBe(false)
  })

  it('renders view-more button when count exceeds items length and viewMoreRoute is set', async () => {
    const cols: BoardColumn[] = [
      {
        status: 'completed',
        label: 'Completed',
        count: 151,
        items: [
          { id: 1, title: 'Task 1', subtitle: 'sub', meta: [], route: '/tasks/1' },
          { id: 2, title: 'Task 2', subtitle: 'sub', meta: [], route: '/tasks/2' },
        ],
        viewMoreRoute: '/tasks?status=completed&initiator_username=alice',
      },
    ]
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns: cols,
        issueTotal: 1,
        taskTotal: 151,
        visibleLimit: 20,
        isMobile: false,
      },
    })

    await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
    const btn = wrapper.find('[data-testid="my-work-board-view-more-tasks-completed"]')
    expect(btn.exists()).toBe(true)
    expect(btn.text()).toContain('dashboard.myWorkBoard.viewMore')
  })

  it('hides view-more button when count equals items length', async () => {
    const cols: BoardColumn[] = [
      {
        status: 'completed',
        label: 'Completed',
        count: 2,
        items: [
          { id: 1, title: 'Task 1', subtitle: 'sub', meta: [], route: '/tasks/1' },
          { id: 2, title: 'Task 2', subtitle: 'sub', meta: [], route: '/tasks/2' },
        ],
        viewMoreRoute: '/tasks?status=completed&initiator_username=alice',
      },
    ]
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns: cols,
        issueTotal: 1,
        taskTotal: 2,
        visibleLimit: 20,
        isMobile: false,
      },
    })

    await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
    expect(wrapper.find('[data-testid="my-work-board-view-more-tasks-completed"]').exists()).toBe(false)
  })

  it('emits viewMore with the route when view-more button is clicked', async () => {
    const cols: BoardColumn[] = [
      {
        status: 'completed',
        label: 'Completed',
        count: 10,
        items: [
          { id: 1, title: 'Task 1', subtitle: 'sub', meta: [], route: '/tasks/1' },
        ],
        viewMoreRoute: '/tasks?status=completed&initiator_username=alice',
      },
    ]
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns: cols,
        issueTotal: 1,
        taskTotal: 10,
        visibleLimit: 20,
        isMobile: false,
      },
    })

    await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
    await wrapper.find('[data-testid="my-work-board-view-more-tasks-completed"]').trigger('click')
    expect(wrapper.emitted('viewMore')).toBeTruthy()
    expect(wrapper.emitted('viewMore')![0]).toEqual(['/tasks?status=completed&initiator_username=alice'])
  })

  it('hides view-more button when viewMoreRoute is not set even if count exceeds items', async () => {
    const cols: BoardColumn[] = [
      {
        status: 'completed',
        label: 'Completed',
        count: 10,
        items: [
          { id: 1, title: 'Task 1', subtitle: 'sub', meta: [], route: '/tasks/1' },
        ],
      },
    ]
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns: cols,
        issueTotal: 1,
        taskTotal: 10,
        visibleLimit: 20,
        isMobile: false,
      },
    })

    await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
    expect(wrapper.find('[data-testid="my-work-board-view-more-tasks-completed"]').exists()).toBe(false)
  })

  it('notice data-testid matches active tab', async () => {
    const wrapper = mount(MyWorkBoard, {
      props: {
        issueColumns,
        taskColumns,
        issueTotal: 1,
        taskTotal: 25,
        visibleLimit: 20,
        isMobile: false,
      },
    })
    expect(wrapper.find('[data-testid="my-work-board-notice-issues"]').exists()).toBe(false)

    await wrapper.find('[data-testid="my-work-board-tab-tasks"]').trigger('click')
    expect(wrapper.find('[data-testid="my-work-board-notice-tasks"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="my-work-board-notice-issues"]').exists()).toBe(false)
  })
})
