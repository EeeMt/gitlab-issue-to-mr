import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { computed, h, ref } from 'vue'
import SystemStatistics from './SystemStatistics.vue'

const { mockApi, resetMockApi } = vi.hoisted(() => {
  const overview = {
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    current_state: {
      pending: 1,
      queued: 2,
      running: 0,
      long_running: 0,
      active_issues: 1,
      avg_queue_wait_seconds: null,
      queue_wait_samples: 0,
    },
    lifetime: {
      issue_count: 3,
      task_count: 5,
      completed: 2,
      failed: 1,
      cancelled: 0,
      finished: 3,
      success_rate: 2 / 3,
      failure_rate: 1 / 3,
      issues_with_mr: 2,
      known_total_tokens: 100,
      known_total_changes: 20,
      known_total_execution_seconds: 300,
      avg_execution_seconds: 150,
      execution_valid_samples: 2,
    },
    deletion: {
      deleted_task_count: 1,
      deleted_issue_count: 1,
      deleted_before_terminal: 0,
    },
    coverage: {
      capture_started_at: '2026-08-01T00:00:00Z',
      capture_enabled: true,
      token: {
        eligible_samples: 3,
        complete_samples: 2,
        partial_samples: 1,
        missing_samples: 0,
        coverage_rate: 2 / 3,
      },
      code: {
        eligible_samples: 2,
        available_samples: 1,
        coverage_rate: 0.5,
      },
    },
  }

  const mock = {
    getSystemStatisticsOverview: vi.fn(),
    getSystemStatisticsTrends: vi.fn(),
    getSystemStatisticsBreakdowns: vi.fn(),
  }

  mock.getSystemStatisticsOverview.mockResolvedValue(overview)
  mock.getSystemStatisticsTrends.mockResolvedValue({
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    range: 'all',
    bucket: 'day',
    series: [],
  })
  mock.getSystemStatisticsBreakdowns.mockResolvedValue({
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    projects: [],
    providers: [],
    harnesses: [],
  })

  return {
    mockApi: mock,
    resetMockApi: () => Object.values(mock).forEach(fn => fn.mockReset()),
  }
})

vi.mock('../api', () => ({
  getSystemStatisticsOverview: mockApi.getSystemStatisticsOverview,
  getSystemStatisticsTrends: mockApi.getSystemStatisticsTrends,
  getSystemStatisticsBreakdowns: mockApi.getSystemStatisticsBreakdowns,
}))

vi.mock('vue-echarts', () => ({
  default: {
    name: 'VChart',
    props: ['option', 'autoresize'],
    setup(_props: any, { attrs }: any) {
      return () => h('div', { ...attrs, class: 'v-chart-stub' })
    },
  },
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('@vicons/ionicons5', () => ({
  RefreshOutline: {},
}))

const breakpoints = vi.hoisted(() => ({ width: 1200 }))

vi.mock('../composables/useBreakpoints', () => ({
  useBreakpoints: () => ({
    isMobile: ref(false),
    isCompact: ref(false),
    width: computed(() => breakpoints.width),
  }),
}))

vi.mock('../components/PageHeader.vue', () => ({
  default: {
    name: 'PageHeader',
    props: ['title', 'subtitle'],
    setup(props: any, { slots }: any) {
      return () => h('div', { class: 'page-header' }, [
        h('h1', props.title),
        h('div', props.subtitle),
        slots.actions?.(),
      ])
    },
  },
}))

function slotStub(name: string, slots: ('default' | 'header' | 'icon' | 'actions')[] = ['default', 'header', 'icon', 'actions']) {
  return {
    name,
    props: ['value', 'options', 'description', 'columns', 'data', 'loading', 'disabled'],
    emits: ['update:value'],
    setup(_props: any, { attrs, slots: s, emit }: any) {
      return () =>
        h('div', { ...attrs, class: [`naive-stub-${name}`, attrs.class] }, [
          slots.includes('header') ? s.header?.() : null,
          slots.includes('icon') ? s.icon?.() : null,
          slots.includes('actions') ? s.actions?.() : null,
          slots.includes('default') ? s.default?.() : null,
        ])
    },
  }
}

vi.mock('naive-ui', () => ({
  NAlert: slotStub('NAlert', ['header', 'default']),
  NButton: slotStub('NButton', ['icon', 'default']),
  NCard: slotStub('NCard', ['header', 'default', 'action']),
  NDataTable: slotStub('NDataTable', []),
  NEmpty: slotStub('NEmpty', ['default']),
  NGi: slotStub('NGi', ['default']),
  NGrid: slotStub('NGrid', ['default']),
  NIcon: slotStub('NIcon', []),
  NSpin: slotStub('NSpin', ['default']),
  NSelect: {
    name: 'NSelect',
    props: ['value', 'options'],
    emits: ['update:value'],
    setup(props: any, { attrs, emit }: any) {
      return () =>
        h(
          'select',
          {
            ...attrs,
            value: props.value,
            onChange: (event: any) => emit('update:value', event.target.value),
          },
          (props.options ?? []).map((opt: any) =>
            h('option', { value: opt.value }, opt.label)
          )
        )
    },
  },
}))

let wrapper: ReturnType<typeof mount> | null = null

beforeEach(() => {
  resetMockApi()
  breakpoints.width = 1200
  mockApi.getSystemStatisticsOverview.mockResolvedValue({
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    current_state: {
      pending: 1,
      queued: 2,
      running: 0,
      long_running: 0,
      active_issues: 1,
      avg_queue_wait_seconds: null,
      queue_wait_samples: 0,
    },
    lifetime: {
      issue_count: 3,
      task_count: 5,
      completed: 2,
      failed: 1,
      cancelled: 0,
      finished: 3,
      success_rate: 2 / 3,
      failure_rate: 1 / 3,
      issues_with_mr: 2,
      known_total_tokens: 100,
      known_total_changes: 20,
      known_total_execution_seconds: 300,
      avg_execution_seconds: 150,
      execution_valid_samples: 2,
    },
    deletion: {
      deleted_task_count: 1,
      deleted_issue_count: 1,
      deleted_before_terminal: 0,
    },
    coverage: {
      capture_started_at: '2026-08-01T00:00:00Z',
      capture_enabled: true,
      token: {
        eligible_samples: 3,
        complete_samples: 2,
        partial_samples: 1,
        missing_samples: 0,
        coverage_rate: 2 / 3,
      },
      code: {
        eligible_samples: 2,
        available_samples: 1,
        coverage_rate: 0.5,
      },
    },
  })
  mockApi.getSystemStatisticsTrends.mockResolvedValue({
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    range: 'all',
    bucket: 'day',
    series: [],
  })
  mockApi.getSystemStatisticsBreakdowns.mockResolvedValue({
    as_of: '2026-08-09T00:00:00Z',
    reporting_timezone: 'Asia/Shanghai',
    projects: [],
    providers: [],
    harnesses: [],
  })
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

describe('SystemStatistics', () => {
  it('renders the reference-statistics coverage statement from i18n', async () => {
    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(mockApi.getSystemStatisticsOverview).toHaveBeenCalledWith({
      data_state: 'all',
    })
    const statement = wrapper.find('[data-testid="coverage-statement"]')
    expect(statement.exists()).toBe(true)
    expect(statement.text()).toContain('systemStatistics.coverageStatementBody')
  })

  it('shows the coverage note when the deletion guarantee is not enabled', async () => {
    mockApi.getSystemStatisticsOverview.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      current_state: {
        pending: 0,
        queued: 0,
        running: 0,
        long_running: 0,
        active_issues: 0,
        avg_queue_wait_seconds: null,
        queue_wait_samples: 0,
      },
      lifetime: {
        issue_count: 0,
        task_count: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
        finished: 0,
        success_rate: null,
        failure_rate: null,
        issues_with_mr: 0,
        known_total_tokens: 0,
        known_total_changes: 0,
        known_total_execution_seconds: null,
      },
      deletion: {
        deleted_task_count: 0,
        deleted_issue_count: 0,
        deleted_before_terminal: 0,
      },
      coverage: {
        capture_started_at: null,
        capture_enabled: false,
        token: {
          eligible_samples: 0,
          complete_samples: 0,
          partial_samples: 0,
          missing_samples: 0,
          coverage_rate: null,
        },
        code: {
          eligible_samples: 0,
          available_samples: 0,
          coverage_rate: null,
        },
      },
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.find('[data-testid="coverage-statement"]').text()).toContain(
      'systemStatistics.coverageNotEnabled'
    )
  })

  it('shows the empty state when there is no trend data', async () => {
    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true)
  })

  it('reloads trends when the trend time range filter changes', async () => {
    wrapper = mount(SystemStatistics)
    await flushPromises()

    await wrapper.find('[data-testid="trend-range-select"]').setValue('90d')
    await flushPromises()

    const lastCall = mockApi.getSystemStatisticsTrends.mock.calls.at(-1)?.[0]
    expect(lastCall).toEqual({ data_state: 'all', range: '90d' })
  })

  it('renders lifetime execution time, failure rate and issues-with-MR cards', async () => {
    wrapper = mount(SystemStatistics)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('systemStatistics.lifetime.knownExecutionSeconds')
    expect(text).toContain('systemStatistics.lifetime.avgExecutionSeconds')
    expect(text).toContain('systemStatistics.lifetime.executionValidSamples')
    expect(text).toContain('systemStatistics.lifetime.failureRate')
    expect(text).toContain('systemStatistics.lifetime.issuesWithMr')
    expect(text).toContain('5m') // 300s known_total_execution_seconds
    expect(text).toContain('2m 30s') // 150s avg_execution_seconds
    expect(text).toContain('33.3%') // 1/3 failure_rate
  })

  it('shows em-dashes for unknown lifetime execution seconds and failure rate', async () => {
    mockApi.getSystemStatisticsOverview.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      current_state: {
        pending: 0,
        queued: 0,
        running: 0,
        long_running: 0,
        active_issues: 0,
        avg_queue_wait_seconds: null,
        queue_wait_samples: 0,
      },
      lifetime: {
        issue_count: 0,
        task_count: 0,
        completed: 0,
        failed: 0,
        cancelled: 0,
        finished: 0,
        success_rate: null,
        failure_rate: null,
        issues_with_mr: 0,
        known_total_tokens: null,
        known_total_changes: null,
        known_total_execution_seconds: null,
      },
      deletion: {
        deleted_task_count: 0,
        deleted_issue_count: 0,
        deleted_before_terminal: 0,
      },
      coverage: {
        capture_started_at: null,
        capture_enabled: false,
        token: {
          eligible_samples: 0,
          complete_samples: 0,
          partial_samples: 0,
          missing_samples: 0,
          coverage_rate: null,
        },
        code: {
          eligible_samples: 0,
          available_samples: 0,
          coverage_rate: null,
        },
      },
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    const text = wrapper.text()
    expect(text).toContain('systemStatistics.lifetime.knownExecutionSeconds')
    expect(text).toContain('systemStatistics.lifetime.failureRate')
    expect(text).toContain('—')
  })

  it('renders a line chart per trend series with short bucket axis labels', async () => {
    mockApi.getSystemStatisticsTrends.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      range: '90d',
      bucket: 'day',
      series: [
        {
          time_basis: 'created_at',
          values: [
            { bucket: '2026-08-01T00:00:00', task_count: 2 },
            { bucket: '2026-08-02T00:00:00', task_count: 3 },
          ],
        },
      ],
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    const chartWrapper = wrapper.findComponent({ name: 'VChart' })
    expect(chartWrapper.exists()).toBe(true)
    const option = chartWrapper.props('option') as {
      xAxis: { data: string[]; axisLabel: { formatter: (v: string) => string } }
      tooltip: { formatter: (params: unknown) => string }
      series: { data: number[]; symbol: string }[]
    }
    // The axis keeps the full bucket for the tooltip, while the label is short.
    expect(option.xAxis.data).toEqual(['2026-08-01T00:00:00', '2026-08-02T00:00:00'])
    expect(option.xAxis.axisLabel.formatter('2026-08-02T00:00:00')).toBe('08-02')
    expect(option.series[0].data).toEqual([2, 3])
    // Two or more buckets draw a line without point markers.
    expect(option.series[0].symbol).toBe('none')
    // The tooltip header uses a readable date instead of the raw ISO bucket.
    const tooltipHtml = option.tooltip.formatter([
      { axisValue: '2026-08-02T00:00:00', seriesName: 'Tasks Created', value: 3, marker: '' },
    ])
    expect(tooltipHtml).toContain('2026-08-02')
    expect(tooltipHtml).toContain('Tasks Created: 3')
  })

  it('shows a visible point for a single-bucket trend series', async () => {
    mockApi.getSystemStatisticsTrends.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      range: '90d',
      bucket: 'day',
      series: [
        {
          time_basis: 'created_at',
          values: [{ bucket: '2026-08-02T00:00:00', task_count: 3 }],
        },
      ],
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    const option = wrapper.findComponent({ name: 'VChart' }).props('option') as {
      series: { symbol: string }[]
    }
    expect(option.series[0].symbol).toBe('circle')
  })

  it('renders placeholders for empty trend series to keep the 4-chart layout', async () => {
    mockApi.getSystemStatisticsTrends.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      range: 'all',
      bucket: 'week',
      series: [
        {
          time_basis: 'source_deleted_at',
          values: [],
        },
        {
          time_basis: 'created_at',
          values: [{ bucket: '2026-08-02T00:00:00', task_count: 3 }],
        },
      ],
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.findAll('.v-chart-stub').length).toBe(1)
    expect(wrapper.findAll('[data-testid="trend-empty"]').length).toBe(3)
    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(false)
  })

  it('shows the global empty state when there is no trend series at all', async () => {
    mockApi.getSystemStatisticsTrends.mockResolvedValue({
      as_of: '2026-08-09T00:00:00Z',
      reporting_timezone: 'Asia/Shanghai',
      range: 'all',
      bucket: 'week',
      series: [],
    })

    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.findAll('.v-chart-stub').length).toBe(0)
    expect(wrapper.find('[data-testid="empty-state"]').exists()).toBe(true)
  })

  it('stacks the breakdown tables below the stack breakpoint to avoid overflow', async () => {
    breakpoints.width = 1366
    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.find('[data-testid="breakdown-grid"]').attributes('cols')).toBe('1')
  })

  it('stacks the breakdown tables at 1440 to prevent silent column clipping', async () => {
    // Round-3 review: with the breakdown card chrome (12px padding + 1px
    // border per side) a half-width table only fits its ≈520px columns once
    // the viewport is ≥1470px wide, so 1440 must stay stacked.
    breakpoints.width = 1440
    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.find('[data-testid="breakdown-grid"]').attributes('cols')).toBe('1')
  })

  it('keeps the two-column breakdown layout at wide viewports', async () => {
    breakpoints.width = 1500
    wrapper = mount(SystemStatistics)
    await flushPromises()

    expect(wrapper.find('[data-testid="breakdown-grid"]').attributes('cols')).toBe('2')
  })

  it('wraps each breakdown table in its own card container', async () => {
    wrapper = mount(SystemStatistics)
    await flushPromises()

    const cards = wrapper.findAll('[data-testid="breakdown-card"]')
    expect(cards.length).toBe(3)
    cards.forEach((card) => {
      expect(card.classes()).toContain('system-statistics-breakdown')
    })
  })
})
