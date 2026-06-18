import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import WebhookEventsPanel from './WebhookEventsPanel.vue'

const { mockGetWebhookEvents } = vi.hoisted(() => ({
  mockGetWebhookEvents: vi.fn(),
}))

vi.mock('../../api', () => ({
  getWebhookEvents: mockGetWebhookEvents,
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('naive-ui', () => ({
  NButton: {
    name: 'NButton',
    props: ['loading'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', {
        class: 'n-button',
        disabled: props.loading,
        onClick: () => emit('click'),
      }, slots.default?.())
    },
  },
  NCard: {
    name: 'NCard',
    setup(_props: any, { slots }: any) {
      return () => h('section', { class: 'n-card' }, [
        h('header', slots.header?.()),
        h('div', slots.default?.()),
      ])
    },
  },
  NDataTable: {
    name: 'NDataTable',
    props: ['columns', 'data', 'rowKey'],
    setup(props: any, { slots }: any) {
      return () => {
        if (!props.data?.length) {
          return h('div', { class: 'n-data-table' }, slots.empty?.())
        }
        return h('div', { class: 'n-data-table' }, [
          h('div', { class: 'n-data-table-header' }, props.columns.map((column: any) =>
            h('span', { class: 'n-data-table-header-cell' }, column.title),
          )),
          ...props.data.map((row: any) =>
            h('div', { class: 'n-data-table-row', key: props.rowKey(row) }, props.columns.map((column: any) => {
              const content = column.render ? column.render(row) : row[column.key]
              return h('span', { class: 'n-data-table-cell', 'data-column-key': column.key }, content)
            })),
          ),
        ])
      }
    },
  },
  NGi: {
    name: 'NGi',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-gi' }, slots.default?.())
    },
  },
  NGrid: {
    name: 'NGrid',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-grid' }, slots.default?.())
    },
  },
  NInputNumber: {
    name: 'NInputNumber',
    props: ['value', 'placeholder'],
    setup(props: any, { emit }: any) {
      return () => h('input', {
        class: 'n-input-number',
        placeholder: props.placeholder,
        value: props.value ?? '',
        onInput: (event: Event) => emit('update:value', Number((event.target as HTMLInputElement).value)),
      })
    },
  },
  NPagination: {
    name: 'NPagination',
    setup() {
      return () => h('nav', { class: 'n-pagination' })
    },
  },
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options', 'placeholder'],
    setup(props: any, { emit }: any) {
      return () => h('select', {
        class: 'n-select',
        value: props.value ?? '',
        onChange: (event: Event) => emit('update:value', (event.target as HTMLSelectElement).value),
      }, [
        h('option', { value: '' }, props.placeholder),
        ...(props.options ?? []).map((option: any) => h('option', { value: option.value }, option.label)),
      ])
    },
  },
  NSpace: {
    name: 'NSpace',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NTag: {
    name: 'NTag',
    setup(_props: any, { slots }: any) {
      return () => h('span', { class: 'n-tag' }, slots.default?.())
    },
  },
}))

describe('WebhookEventsPanel', () => {
  beforeEach(() => {
    mockGetWebhookEvents.mockReset()
    mockGetWebhookEvents.mockResolvedValue({
      items: [
        {
          id: 1,
          event_type: 'pipeline',
          event_action: 'failed',
          project_id: 42,
          merge_request_iid: 8,
          issue_id: 12,
          source_ip: null,
          result: 'ci_failure_collecting',
          result_detail: 'Pipeline 1001 failed; CI failure collection queued',
          payload_summary: { pipeline_id: 1001 },
          created_at: '2024-01-03T10:00:00Z',
        },
        {
          id: 2,
          event_type: 'merge_request',
          event_action: 'merge',
          project_id: 42,
          merge_request_iid: 8,
          issue_id: 12,
          source_ip: null,
          result: 'issue_closed',
          result_detail: null,
          payload_summary: { mr_title: 'Fix bug' },
          created_at: '2024-01-03T10:02:00Z',
        },
      ],
      total: 2,
      page: 1,
      page_size: 20,
    })
  })

  it('renders pipeline id from webhook payload summary', async () => {
    const wrapper = mount(WebhookEventsPanel, {
      props: { isMobile: false },
      global: {
        stubs: {
          RouterLink: {
            props: ['to'],
            template: '<a><slot /></a>',
          },
        },
      },
    })

    await flushPromises()

    expect(mockGetWebhookEvents).toHaveBeenCalledWith({
      page: 1,
      page_size: 20,
      result: undefined,
      project_id: undefined,
    })
    expect(wrapper.text()).toContain('config.webhookEventsColPipelineId')
    expect(wrapper.text()).toContain('1001')
  })
})
