# Analytics Providers V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a top-level Providers tab to Analytics that compares AI providers by task volume, tokens, success rate, and efficiency metrics using the existing `/api/stats/analytics` endpoint and the current lightweight chart/card approach.

**Architecture:** Extend `backend/app/api/stats.py` to compute provider-level aggregates from the same filtered task universe already used by Analytics, then expose those aggregates as `provider_summary`, `providers`, and `provider_chart_series` in the existing analytics payload. Update the shared frontend analytics types in `frontend/src/api/index.ts`, then add a Providers tab in `frontend/src/views/Analytics.vue` that reuses the page's existing filter controls, summary-card patterns, table patterns, and lightweight bar-style visualizations without introducing ECharts.

**Tech Stack:** FastAPI, SQLAlchemy, Python 3.11, Vue 3, TypeScript, Naive UI, vue-i18n, Vitest, vue-test-utils

---

## File Map

- `backend/app/api/stats.py`
  - Add provider analytics helpers and queries inside `get_analytics`.
  - Reuse the current access-scope, project, initiator, and date-window filter flow.
  - Return `provider_summary`, `providers`, and `provider_chart_series` in the analytics payload.
- `backend/tests/unit/test_task_analytics_api.py`
  - Add failing tests first for provider payload structure, null-provider grouping, denominator-sensitive metrics, and filter consistency.
- `frontend/src/api/index.ts`
  - Extend `AnalyticsResponse` with provider types used by the frontend.
- `frontend/src/views/Analytics.vue`
  - Add top-level `Overview / Providers` tabs.
  - Add provider summary cards, provider comparison table, provider charts, and provider empty state.
  - Keep shared filters and refresh behavior unchanged.
- `frontend/src/views/Analytics.spec.ts`
  - Add failing tests first for tab switching, provider empty state, `N/A` rendering, and provider chart toggle behavior.
- `frontend/src/i18n/messages/en.ts`
  - Add English copy for new Providers tab labels, cards, table headings, chart toggles, and empty state.
- `frontend/src/i18n/messages/zh-CN.ts`
  - Add matching Chinese copy for the same keys.

---

### Task 1: Lock the backend provider payload with failing tests

**Files:**
- Modify: `backend/tests/unit/test_task_analytics_api.py`
- Test: `backend/tests/unit/test_task_analytics_api.py`

- [ ] **Step 1: Write the failing provider analytics test**

Add a new test below the existing analytics API test:

```py
@pytest.mark.asyncio
async def test_get_analytics_returns_provider_metrics_and_unknown_legacy_bucket():
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)
    db = MagicMock()
    call_count = [0]

    def execute_side_effect(query):
        call_count[0] += 1

        if call_count[0] == 1:
            return MockResult([
                6, 30, 10, 40, 1600, 2400, 3, 2, 1, 6, 4, 4,
                datetime(2026, 3, 12, 8, 0, 0), 600.0, 900.0, 120.0, 240.0, 1000.0, 1400.0,
            ])
        if call_count[0] == 2:
            return MockResult([])
        if call_count[0] == 3:
            return MockResult([])
        if call_count[0] == 4:
            return MockResult([])
        if call_count[0] == 5:
            return MockResult([])
        if call_count[0] == 6:
            return MockResult([])
        if call_count[0] == 7:
            return MockResult([])
        if call_count[0] == 8:
            return MockResult([])
        if call_count[0] == 9:
            return MockResult([])
        if call_count[0] == 10:
            return MockResult([
                SimpleNamespace(
                    provider_id=1,
                    provider_name='Claude Sonnet',
                    provider_model='claude-sonnet-4-6',
                    task_count=3,
                    completed_tasks=2,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    finished_tasks=3,
                    total_input_tokens=600,
                    total_output_tokens=900,
                    total_tokens=1500,
                    avg_tokens_per_task=500.0,
                    avg_tokens_per_second=4.0,
                    avg_tokens_per_changed_line=12.0,
                    avg_execution_seconds=300.0,
                    avg_execution_seconds_per_changed_line=3.0,
                ),
                SimpleNamespace(
                    provider_id=None,
                    provider_name=None,
                    provider_model=None,
                    task_count=2,
                    completed_tasks=1,
                    failed_tasks=0,
                    cancelled_tasks=1,
                    finished_tasks=2,
                    total_input_tokens=200,
                    total_output_tokens=300,
                    total_tokens=500,
                    avg_tokens_per_task=250.0,
                    avg_tokens_per_second=None,
                    avg_tokens_per_changed_line=None,
                    avg_execution_seconds=450.0,
                    avg_execution_seconds_per_changed_line=None,
                ),
            ])
        raise AssertionError(f'unexpected execute call #{call_count[0]}')

    db.execute = AsyncMock(side_effect=execute_side_effect)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch('app.api.stats.utcnow', return_value=fixed_now), patch(
        'app.api.stats.build_project_lookup', new=AsyncMock(return_value={})
    ):
        response = await get_analytics(
            days=7,
            project_id=None,
            initiator_username=None,
            db=db,
            _current_user=None,
            access_scope=access_scope,
        )

    assert response['provider_summary']['active_provider_count'] == 2
    assert response['provider_summary']['provider_covered_task_count'] == 5
    assert response['provider_summary']['provider_covered_total_tokens'] == 2000
    assert response['provider_summary']['provider_success_rate'] == pytest.approx(3 / 5)

    assert response['providers'][0]['provider_name'] == 'Claude Sonnet'
    assert response['providers'][0]['provider_model'] == 'claude-sonnet-4-6'
    assert response['providers'][0]['avg_tokens_per_second'] == pytest.approx(4.0)

    assert response['providers'][1]['provider_name'] == 'Unknown / Legacy'
    assert response['providers'][1]['provider_model'] is None
    assert response['providers'][1]['avg_tokens_per_second'] is None
    assert response['providers'][1]['avg_tokens_per_changed_line'] is None
    assert response['providers'][1]['avg_execution_seconds_per_changed_line'] is None

    assert response['provider_chart_series']['success_rate'][0]['label'] == 'Claude Sonnet / claude-sonnet-4-6'
    assert response['provider_chart_series']['avg_tokens_per_second'][0]['value'] == pytest.approx(4.0)
```

- [ ] **Step 2: Run the backend test to verify it fails**

Run: `pytest backend/tests/unit/test_task_analytics_api.py::test_get_analytics_returns_provider_metrics_and_unknown_legacy_bucket -v`

Expected: FAIL because `get_analytics` does not yet return `provider_summary`, `providers`, or `provider_chart_series`.

- [ ] **Step 3: Add a second failing test for denominator-sensitive null metrics**

Add:

```py
@pytest.mark.asyncio
async def test_get_analytics_provider_metrics_return_null_when_denominator_missing():
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)
    db = MagicMock()
    call_count = [0]

    def execute_side_effect(query):
        call_count[0] += 1
        if call_count[0] <= 9:
            return MockResult([] if call_count[0] != 1 else [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, None, None, None, None, None, None, None])
        if call_count[0] == 10:
            return MockResult([
                SimpleNamespace(
                    provider_id=2,
                    provider_name='GPT-4.1',
                    provider_model='gpt-4.1',
                    task_count=1,
                    completed_tasks=0,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    finished_tasks=0,
                    total_input_tokens=0,
                    total_output_tokens=0,
                    total_tokens=0,
                    avg_tokens_per_task=None,
                    avg_tokens_per_second=None,
                    avg_tokens_per_changed_line=None,
                    avg_execution_seconds=None,
                    avg_execution_seconds_per_changed_line=None,
                )
            ])
        raise AssertionError(f'unexpected execute call #{call_count[0]}')

    db.execute = AsyncMock(side_effect=execute_side_effect)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch('app.api.stats.utcnow', return_value=fixed_now), patch(
        'app.api.stats.build_project_lookup', new=AsyncMock(return_value={})
    ):
        response = await get_analytics(7, None, None, db, None, access_scope)

    row = response['providers'][0]
    assert row['success_rate'] is None
    assert row['avg_tokens_per_task'] is None
    assert row['avg_tokens_per_second'] is None
    assert row['avg_tokens_per_changed_line'] is None
    assert row['avg_execution_seconds'] is None
    assert row['avg_execution_seconds_per_changed_line'] is None
```

- [ ] **Step 4: Run both new backend tests to verify red**

Run: `pytest backend/tests/unit/test_task_analytics_api.py -k provider -v`

Expected: FAIL only because provider analytics behavior is missing.

- [ ] **Step 5: Commit the red backend tests**

```bash
git add backend/tests/unit/test_task_analytics_api.py
git commit -m "test: cover analytics provider metrics"
```

---

### Task 2: Implement backend provider analytics payload

**Files:**
- Modify: `backend/app/api/stats.py`
- Test: `backend/tests/unit/test_task_analytics_api.py`

- [ ] **Step 1: Add focused helper functions near the other analytics helpers**

In `backend/app/api/stats.py`, add helpers after `_build_status_breakdown_rows`:

```py
def _safe_ratio(numerator: int | float | None, denominator: int | float | None) -> float | None:
    if denominator in (None, 0):
        return None
    if numerator is None:
        return None
    return float(numerator) / float(denominator)


def _provider_display_label(provider_name: str | None, provider_model: str | None) -> str:
    if not provider_name:
        return 'Unknown / Legacy'
    return f'{provider_name} / {provider_model}' if provider_model else provider_name


def _build_provider_chart_series(rows: list[dict]) -> dict:
    def build(metric_key: str) -> list[dict]:
        return [
            {
                'provider_id': row['provider_id'],
                'label': _provider_display_label(row['provider_name'], row['provider_model']),
                'value': row[metric_key],
            }
            for row in rows
            if row[metric_key] is not None
        ]

    return {
        'success_rate': build('success_rate'),
        'avg_tokens_per_second': build('avg_tokens_per_second'),
        'avg_tokens_per_changed_line': build('avg_tokens_per_changed_line'),
        'avg_execution_seconds_per_changed_line': build('avg_execution_seconds_per_changed_line'),
    }
```

- [ ] **Step 2: Add the provider aggregate query inside `get_analytics`**

After the existing `error_breakdown` query, add a provider query that groups by `Task.provider_id`, `Task.provider_name`, and `Task.model_name`:

```py
    provider_query = (
        select(
            Task.provider_id.label('provider_id'),
            func.max(Task.provider_name).label('provider_name'),
            func.max(Task.model_name).label('provider_model'),
            func.count(Task.id).label('task_count'),
            func.coalesce(func.sum(case((Task.status == TaskStatus.COMPLETED, 1), else_=0)), 0).label('completed_tasks'),
            func.coalesce(func.sum(case((Task.status == TaskStatus.FAILED, 1), else_=0)), 0).label('failed_tasks'),
            func.coalesce(func.sum(case((Task.status == TaskStatus.CANCELLED, 1), else_=0)), 0).label('cancelled_tasks'),
            func.coalesce(func.sum(finished_task_expr), 0).label('finished_tasks'),
            func.coalesce(func.sum(Task.input_tokens), 0).label('total_input_tokens'),
            func.coalesce(func.sum(Task.output_tokens), 0).label('total_output_tokens'),
            func.coalesce(func.sum(token_total_expr), 0).label('total_tokens'),
            func.avg(case((token_total_expr.is_not(None), token_total_expr), else_=None)).label('avg_tokens_per_task'),
            func.avg(
                case(
                    ((token_total_expr.is_not(None)) & (execution_seconds_expr.is_not(None)) & (execution_seconds_expr > 0), token_total_expr / execution_seconds_expr),
                    else_=None,
                )
            ).label('avg_tokens_per_second'),
            func.avg(
                case(
                    ((token_total_expr.is_not(None)) & (Task.total_changes.is_not(None)) & (Task.total_changes > 0), token_total_expr / Task.total_changes),
                    else_=None,
                )
            ).label('avg_tokens_per_changed_line'),
            func.avg(execution_seconds_expr).label('avg_execution_seconds'),
            func.avg(
                case(
                    ((execution_seconds_expr.is_not(None)) & (Task.total_changes.is_not(None)) & (Task.total_changes > 0), execution_seconds_expr / Task.total_changes),
                    else_=None,
                )
            ).label('avg_execution_seconds_per_changed_line'),
        )
        .where(Task.created_at >= since, (Task.provider_id.is_not(None)) | (Task.provider_name.is_not(None)) | (Task.model_name.is_not(None)))
        .group_by(Task.provider_id)
        .order_by(func.count(Task.id).desc(), func.coalesce(func.sum(token_total_expr), 0).desc(), Task.provider_id.asc())
    )
    provider_query = _apply_analytics_filters(
        provider_query,
        access_scope,
        project_id=project_id,
        initiator_username=selected_initiator_username,
    )
    provider_rows = (await db.execute(provider_query)).all()
```

- [ ] **Step 3: Normalize `Unknown / Legacy` and build response rows**

Turn `provider_rows` into response dictionaries before the final return:

```py
    provider_items: list[dict] = []
    for row in provider_rows:
        provider_name = row.provider_name or 'Unknown / Legacy'
        provider_model = row.provider_model if row.provider_name else None
        finished_count = int(row.finished_tasks or 0)
        completed_count = int(row.completed_tasks or 0)

        provider_items.append(
            {
                'provider_id': int(row.provider_id) if row.provider_id is not None else None,
                'provider_name': provider_name,
                'provider_model': provider_model,
                'task_count': int(row.task_count or 0),
                'finished_task_count': finished_count,
                'completed_task_count': completed_count,
                'failed_task_count': int(row.failed_tasks or 0),
                'cancelled_task_count': int(row.cancelled_tasks or 0),
                'success_rate': _safe_ratio(completed_count, finished_count),
                'total_input_tokens': int(row.total_input_tokens or 0),
                'total_output_tokens': int(row.total_output_tokens or 0),
                'total_tokens': int(row.total_tokens or 0),
                'avg_tokens_per_task': float(row.avg_tokens_per_task) if row.avg_tokens_per_task is not None else None,
                'avg_tokens_per_second': float(row.avg_tokens_per_second) if row.avg_tokens_per_second is not None else None,
                'avg_tokens_per_changed_line': float(row.avg_tokens_per_changed_line) if row.avg_tokens_per_changed_line is not None else None,
                'avg_execution_seconds': float(row.avg_execution_seconds) if row.avg_execution_seconds is not None else None,
                'avg_execution_seconds_per_changed_line': float(row.avg_execution_seconds_per_changed_line) if row.avg_execution_seconds_per_changed_line is not None else None,
            }
        )

    provider_summary = {
        'active_provider_count': len(provider_items),
        'provider_covered_task_count': sum(item['task_count'] for item in provider_items),
        'provider_covered_total_tokens': sum(item['total_tokens'] for item in provider_items),
        'provider_success_rate': _safe_ratio(
            sum(item['completed_task_count'] for item in provider_items),
            sum(item['finished_task_count'] for item in provider_items),
        ),
    }
```

- [ ] **Step 4: Add provider payload sections to the final response**

In the `return` dict from `get_analytics`, append:

```py
        'provider_summary': provider_summary,
        'providers': provider_items,
        'provider_chart_series': _build_provider_chart_series(provider_items),
```

- [ ] **Step 5: Run the focused backend tests to verify green**

Run: `pytest backend/tests/unit/test_task_analytics_api.py -k provider -v`

Expected: PASS.

- [ ] **Step 6: Run the full backend analytics unit file**

Run: `pytest backend/tests/unit/test_task_analytics_api.py -v`

Expected: PASS, including the existing analytics response test.

- [ ] **Step 7: Commit the backend implementation**

```bash
git add backend/app/api/stats.py backend/tests/unit/test_task_analytics_api.py
git commit -m "feat: add analytics provider aggregates"
```

---

### Task 3: Extend frontend API types for provider analytics

**Files:**
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add the failing type usage in the view test first**

Before editing `src/api/index.ts`, add this temporary access in `frontend/src/views/Analytics.spec.ts` near `mockAnalytics` usage:

```ts
const providerRows = mockAnalytics.providers
expect(providerRows?.length ?? 0).toBeGreaterThanOrEqual(0)
```

This should fail at type-check/build time because `AnalyticsResponse` does not yet define `providers`.

- [ ] **Step 2: Add provider analytics interfaces in `frontend/src/api/index.ts`**

Insert after `AnalyticsStatusRow`:

```ts
export interface AnalyticsProviderSummary {
  active_provider_count: number
  provider_covered_task_count: number
  provider_covered_total_tokens: number
  provider_success_rate: number | null
}

export interface AnalyticsProviderRow {
  provider_id: number | null
  provider_name: string
  provider_model: string | null
  task_count: number
  finished_task_count: number
  completed_task_count: number
  failed_task_count: number
  cancelled_task_count: number
  success_rate: number | null
  total_input_tokens: number
  total_output_tokens: number
  total_tokens: number
  avg_tokens_per_task: number | null
  avg_tokens_per_second: number | null
  avg_tokens_per_changed_line: number | null
  avg_execution_seconds: number | null
  avg_execution_seconds_per_changed_line: number | null
}

export interface AnalyticsProviderChartPoint {
  provider_id: number | null
  label: string
  value: number
}

export interface AnalyticsProviderChartSeries {
  success_rate: AnalyticsProviderChartPoint[]
  avg_tokens_per_second: AnalyticsProviderChartPoint[]
  avg_tokens_per_changed_line: AnalyticsProviderChartPoint[]
  avg_execution_seconds_per_changed_line: AnalyticsProviderChartPoint[]
}
```

- [ ] **Step 3: Extend `AnalyticsResponse`**

Update the interface:

```ts
export interface AnalyticsResponse {
  window_days: number
  generated_at: string
  summary: AnalyticsSummary
  available_initiators: AnalyticsInitiatorOption[]
  projects: AnalyticsProjectRow[]
  initiators: AnalyticsInitiatorRow[]
  trends: AnalyticsTrendPoint[]
  priority_waits: AnalyticsPriorityWaitRow[]
  issue_status_breakdown: AnalyticsStatusRow[]
  task_status_breakdown: AnalyticsStatusRow[]
  error_breakdown: AnalyticsErrorRow[]
  provider_summary: AnalyticsProviderSummary
  providers: AnalyticsProviderRow[]
  provider_chart_series: AnalyticsProviderChartSeries
}
```

- [ ] **Step 4: Run the frontend type check to verify green**

Run: `cd frontend && npm run build`

Expected: PASS or move on to the next task if the build now fails only because `Analytics.vue` does not yet use the new payload safely.

- [ ] **Step 5: Commit the type extension**

```bash
git add frontend/src/api/index.ts frontend/src/views/Analytics.spec.ts
git commit -m "refactor: add analytics provider response types"
```

---

### Task 4: Lock Providers tab behavior with failing frontend tests

**Files:**
- Modify: `frontend/src/views/Analytics.spec.ts`
- Test: `frontend/src/views/Analytics.spec.ts`

- [ ] **Step 1: Extend the mocked analytics fixture with provider data**

Add to `mockAnalytics`:

```ts
  provider_summary: {
    active_provider_count: 2,
    provider_covered_task_count: 6,
    provider_covered_total_tokens: 50000,
    provider_success_rate: 0.75
  },
  providers: [
    {
      provider_id: 1,
      provider_name: 'Claude Sonnet',
      provider_model: 'claude-sonnet-4-6',
      task_count: 4,
      finished_task_count: 4,
      completed_task_count: 3,
      failed_task_count: 1,
      cancelled_task_count: 0,
      success_rate: 0.75,
      total_input_tokens: 30000,
      total_output_tokens: 15000,
      total_tokens: 45000,
      avg_tokens_per_task: 11250,
      avg_tokens_per_second: 4.5,
      avg_tokens_per_changed_line: 30,
      avg_execution_seconds: 400,
      avg_execution_seconds_per_changed_line: 6
    },
    {
      provider_id: null,
      provider_name: 'Unknown / Legacy',
      provider_model: null,
      task_count: 2,
      finished_task_count: 2,
      completed_task_count: 1,
      failed_task_count: 0,
      cancelled_task_count: 1,
      success_rate: 0.5,
      total_input_tokens: 3000,
      total_output_tokens: 2000,
      total_tokens: 5000,
      avg_tokens_per_task: 2500,
      avg_tokens_per_second: null,
      avg_tokens_per_changed_line: null,
      avg_execution_seconds: 500,
      avg_execution_seconds_per_changed_line: null
    }
  ],
  provider_chart_series: {
    success_rate: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 0.75 },
      { provider_id: null, label: 'Unknown / Legacy', value: 0.5 }
    ],
    avg_tokens_per_second: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 4.5 }
    ],
    avg_tokens_per_changed_line: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 30 }
    ],
    avg_execution_seconds_per_changed_line: [
      { provider_id: 1, label: 'Claude Sonnet / claude-sonnet-4-6', value: 6 }
    ]
  },
```

Add an empty-provider fixture:

```ts
const mockAnalyticsEmptyProviders = {
  ...mockAnalytics,
  provider_summary: {
    active_provider_count: 0,
    provider_covered_task_count: 0,
    provider_covered_total_tokens: 0,
    provider_success_rate: null
  },
  providers: [],
  provider_chart_series: {
    success_rate: [],
    avg_tokens_per_second: [],
    avg_tokens_per_changed_line: [],
    avg_execution_seconds_per_changed_line: []
  }
}
```

- [ ] **Step 2: Update the Naive UI tabs stub to support top-level overview/providers tabs**

In the `NTabs` mock, render buttons for the new tabs:

```ts
h('button', {
  class: 'n-tabs__trigger',
  'data-tab': 'overview',
  onClick: () => emit('update:value', 'overview')
}, 'overview'),
h('button', {
  class: 'n-tabs__trigger',
  'data-tab': 'providers',
  onClick: () => emit('update:value', 'providers')
}, 'providers'),
```

Keep the existing breakdown tab buttons or split the stub logic by props if needed.

- [ ] **Step 3: Add failing tests for Providers tab behavior**

Add:

```ts
it('defaults analytics page to overview tab', async () => {
  wrapper = mount(Analytics, mountOptions)
  await flushPromises()

  expect(wrapper.vm.analyticsTab).toBe('overview')
  expect(wrapper.find('[data-testid="analytics-breakdown-card"]').exists()).toBe(true)
})

it('switches to providers tab and renders provider summary cards', async () => {
  wrapper = mount(Analytics, mountOptions)
  await flushPromises()

  await wrapper.find('[data-tab="providers"]').trigger('click')
  await nextTick()

  expect(wrapper.vm.analyticsTab).toBe('providers')
  expect(wrapper.text()).toContain('Claude Sonnet')
  expect(wrapper.text()).toContain('Unknown / Legacy')
})

it('renders provider empty state when provider analytics is empty', async () => {
  ;(mockApi.getAnalytics as Mock).mockResolvedValue(mockAnalyticsEmptyProviders)
  wrapper = mount(Analytics, mountOptions)
  await flushPromises()

  await wrapper.find('[data-tab="providers"]').trigger('click')
  await nextTick()

  expect(wrapper.text()).toContain('No provider analytics match the current filters and time window yet.')
})

it('renders N/A for provider metrics with null denominators', async () => {
  wrapper = mount(Analytics, mountOptions)
  await flushPromises()

  await wrapper.find('[data-tab="providers"]').trigger('click')
  await nextTick()

  expect(wrapper.text()).toContain('N/A')
})
```

- [ ] **Step 4: Run the frontend spec to verify it fails**

Run: `cd frontend && npx vitest run src/views/Analytics.spec.ts`

Expected: FAIL because `Analytics.vue` does not yet expose `analyticsTab` or render provider content.

- [ ] **Step 5: Commit the red frontend tests**

```bash
git add frontend/src/views/Analytics.spec.ts
git commit -m "test: cover analytics providers tab"
```

---

### Task 5: Implement the Providers tab in `Analytics.vue`

**Files:**
- Modify: `frontend/src/views/Analytics.vue`
- Test: `frontend/src/views/Analytics.spec.ts`

- [ ] **Step 1: Add tab state and provider view model types**

Near the existing refs/types in `frontend/src/views/Analytics.vue`, add:

```ts
type AnalyticsTab = 'overview' | 'providers'
type ProviderMetricMode = 'avg_tokens_per_second' | 'avg_tokens_per_changed_line' | 'avg_execution_seconds_per_changed_line'

type ProviderChartBar = {
  key: string
  label: string
  value: number
  displayValue: string
  heightPercent: number
}

const analyticsTab = ref<AnalyticsTab>('overview')
const providerMetricMode = ref<ProviderMetricMode>('avg_tokens_per_second')
```

- [ ] **Step 2: Add provider formatting helpers**

Add helper functions beside the existing formatters:

```ts
function formatProviderLabel(name: string, model: string | null) {
  return model ? `${name} / ${model}` : name
}

function formatMetricNumber(value: number | null | undefined, digits = 1) {
  if (value === null || value === undefined || Number.isNaN(value)) {
    return t('common.notAvailable')
  }
  return value.toLocaleString(undefined, { maximumFractionDigits: digits })
}
```

- [ ] **Step 3: Add provider computed state**

After the existing status chart computeds, add:

```ts
const providerSummaryItems = computed(() => {
  const summary = analytics.value?.provider_summary
  if (!summary) return []
  return [
    { label: t('analytics.activeProviders'), value: String(summary.active_provider_count) },
    { label: t('analytics.providerCoveredTasks'), value: String(summary.provider_covered_task_count) },
    { label: t('analytics.providerCoveredTokens'), value: formatNumber(summary.provider_covered_total_tokens) },
    { label: t('analytics.providerSuccessRate'), value: formatPercentage(summary.provider_success_rate) }
  ]
})

const providerRows = computed(() => analytics.value?.providers || [])
const hasProviderData = computed(() => providerRows.value.length > 0)
const providerEfficiencySeries = computed(() => analytics.value?.provider_chart_series?.[providerMetricMode.value] || [])
const providerSuccessSeries = computed(() => analytics.value?.provider_chart_series?.success_rate || [])

const providerSuccessBars = computed(() =>
  buildTrendBars(
    providerSuccessSeries.value.map((point) => ({
      key: `${point.label}-success`,
      label: point.label,
      value: point.value,
      displayValue: formatPercentage(point.value)
    }))
  )
)

const providerEfficiencyBars = computed(() =>
  buildTrendBars(
    providerEfficiencySeries.value.map((point) => ({
      key: `${point.label}-${providerMetricMode.value}`,
      label: point.label,
      value: point.value,
      displayValue: formatMetricNumber(point.value)
    }))
  )
)
```

- [ ] **Step 4: Add provider table columns**

Add a new computed for the provider table:

```ts
const providerColumns = computed<DataTableColumns<AnalyticsProviderRow>>(() => [
  {
    title: t('analytics.provider'),
    key: 'provider_name',
    minWidth: 220,
    sorter: (a, b) => a.provider_name.localeCompare(b.provider_name),
    render: (row) =>
      h('div', [
        h('div', { style: { fontWeight: 500 } }, row.provider_name),
        row.provider_model
          ? h('div', { style: secondaryTextStyle }, row.provider_model)
          : null
      ])
  },
  { title: t('analytics.tasks'), key: 'task_count', width: 90, sorter: (a, b) => a.task_count - b.task_count },
  {
    title: t('analytics.successRate'),
    key: 'success_rate',
    width: 120,
    sorter: (a, b) => (a.success_rate ?? -1) - (b.success_rate ?? -1),
    render: (row) => formatPercentage(row.success_rate)
  },
  {
    title: t('analytics.totalTokens'),
    key: 'total_tokens',
    width: 120,
    sorter: (a, b) => a.total_tokens - b.total_tokens,
    render: (row) => formatNumber(row.total_tokens)
  },
  {
    title: t('analytics.avgTokensPerTask'),
    key: 'avg_tokens_per_task',
    width: 140,
    sorter: (a, b) => (a.avg_tokens_per_task ?? -1) - (b.avg_tokens_per_task ?? -1),
    render: (row) => formatMetricNumber(row.avg_tokens_per_task)
  },
  {
    title: t('analytics.avgTokensPerSecond'),
    key: 'avg_tokens_per_second',
    width: 150,
    sorter: (a, b) => (a.avg_tokens_per_second ?? -1) - (b.avg_tokens_per_second ?? -1),
    render: (row) => formatMetricNumber(row.avg_tokens_per_second)
  },
  {
    title: t('analytics.avgTokensPerChangedLine'),
    key: 'avg_tokens_per_changed_line',
    width: 170,
    sorter: (a, b) => (a.avg_tokens_per_changed_line ?? -1) - (b.avg_tokens_per_changed_line ?? -1),
    render: (row) => formatMetricNumber(row.avg_tokens_per_changed_line)
  },
  {
    title: t('analytics.avgSecondsPerChangedLine'),
    key: 'avg_execution_seconds_per_changed_line',
    width: 180,
    sorter: (a, b) => (a.avg_execution_seconds_per_changed_line ?? -1) - (b.avg_execution_seconds_per_changed_line ?? -1),
    render: (row) => formatMetricNumber(row.avg_execution_seconds_per_changed_line)
  }
])
```

- [ ] **Step 5: Add the top-level tabs to the template**

Wrap the page body after the alert with top-level tabs:

```vue
<n-tabs v-model:value="analyticsTab" type="segment" size="large" class="analytics-page-tabs">
  <n-tab-pane name="overview" :tab="t('analytics.overviewTab')" />
  <n-tab-pane name="providers" :tab="t('analytics.providersTab')" />
</n-tabs>

<template v-if="analyticsTab === 'overview'">
  <!-- existing summary grid, status cards, trend cards, breakdown card, tables -->
</template>

<template v-else>
  <!-- provider tab content -->
</template>
```

Do not move the existing filters into the tab body.

- [ ] **Step 6: Render the Providers tab body**

Inside the providers branch, add:

```vue
<n-space vertical :size="16">
  <n-grid v-if="hasLoadedOnce" :cols="isMobile ? 2 : 4" :x-gap="16" :y-gap="16">
    <n-gi v-for="item in providerSummaryItems" :key="item.label" class="analytics-grid-cell">
      <SummaryCard
        :label="item.label"
        :value="item.value"
        card-class="analytics-summary-card"
        label-class="analytics-summary-card__label"
        value-class="analytics-summary-card__value"
      />
    </n-gi>
  </n-grid>

  <div v-if="!hasProviderData" class="analytics-empty-state" data-testid="analytics-providers-empty-state">
    <div class="analytics-empty-state__title">{{ t('analytics.providersEmpty') }}</div>
  </div>

  <template v-else>
    <n-card class="analytics-card analytics-card--stretch" :bordered="false" data-testid="analytics-providers-table-card">
      <template #header>
        <div class="analytics-card__header">
          <div>
            <div class="analytics-card__title">{{ t('analytics.providersComparison') }}</div>
            <div class="analytics-card__subtitle">{{ t('analytics.providersComparisonSubtitle') }}</div>
          </div>
        </div>
      </template>
      <n-data-table
        :columns="providerColumns"
        :data="providerRows"
        :bordered="false"
        :pagination="{ pageSize: 8 }"
        :scroll-x="isMobile ? undefined : 1280"
      />
    </n-card>

    <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="16">
      <n-gi class="analytics-grid-cell">
        <n-card class="analytics-card analytics-card--stretch" :bordered="false" data-testid="analytics-provider-success-card">
          <template #header>
            <div class="analytics-card__header">
              <div>
                <div class="analytics-card__title">{{ t('analytics.providerSuccessRateChart') }}</div>
                <div class="analytics-card__subtitle">{{ t('analytics.providerSuccessRateChartSubtitle') }}</div>
              </div>
            </div>
          </template>
          <div class="trend-chart">
            <div v-for="bar in providerSuccessBars" :key="bar.key" class="trend-chart__item">
              <div class="trend-chart__count">{{ bar.displayValue }}</div>
              <div class="trend-chart__bar-wrap">
                <div class="trend-chart__bar trend-chart__bar--accent" :style="{ height: `${bar.heightPercent}%` }" />
              </div>
              <div class="trend-chart__label">{{ bar.label }}</div>
            </div>
          </div>
        </n-card>
      </n-gi>

      <n-gi class="analytics-grid-cell">
        <n-card class="analytics-card analytics-card--stretch" :bordered="false" data-testid="analytics-provider-efficiency-card">
          <template #header>
            <div class="analytics-card__header">
              <div>
                <div class="analytics-card__title">{{ t('analytics.providerEfficiencyChart') }}</div>
                <div class="analytics-card__subtitle">{{ t('analytics.providerEfficiencyChartSubtitle') }}</div>
              </div>
              <div class="analytics-card__header-actions analytics-card__header-actions--status">
                <div class="analytics-chart-toggle" role="tablist" :aria-label="t('analytics.providerEfficiencyChart')">
                  <button type="button" class="analytics-chart-toggle__button" :class="{ 'analytics-chart-toggle__button--active': providerMetricMode === 'avg_tokens_per_second' }" data-testid="provider-metric-mode-tps" @click="providerMetricMode = 'avg_tokens_per_second'">
                    {{ t('analytics.avgTokensPerSecond') }}
                  </button>
                  <button type="button" class="analytics-chart-toggle__button" :class="{ 'analytics-chart-toggle__button--active': providerMetricMode === 'avg_tokens_per_changed_line' }" data-testid="provider-metric-mode-tpcl" @click="providerMetricMode = 'avg_tokens_per_changed_line'">
                    {{ t('analytics.avgTokensPerChangedLine') }}
                  </button>
                  <button type="button" class="analytics-chart-toggle__button" :class="{ 'analytics-chart-toggle__button--active': providerMetricMode === 'avg_execution_seconds_per_changed_line' }" data-testid="provider-metric-mode-spcl" @click="providerMetricMode = 'avg_execution_seconds_per_changed_line'">
                    {{ t('analytics.avgSecondsPerChangedLine') }}
                  </button>
                </div>
              </div>
            </div>
          </template>
          <div class="trend-chart">
            <div v-for="bar in providerEfficiencyBars" :key="bar.key" class="trend-chart__item">
              <div class="trend-chart__count">{{ bar.displayValue }}</div>
              <div class="trend-chart__bar-wrap">
                <div class="trend-chart__bar trend-chart__bar--token" :style="{ height: `${bar.heightPercent}%` }" />
              </div>
              <div class="trend-chart__label">{{ bar.label }}</div>
            </div>
          </div>
        </n-card>
      </n-gi>
    </n-grid>
  </template>
</n-space>
```

- [ ] **Step 7: Run the focused frontend spec to verify green**

Run: `cd frontend && npx vitest run src/views/Analytics.spec.ts`

Expected: PASS.

- [ ] **Step 8: Run the frontend build**

Run: `cd frontend && npm run build`

Expected: PASS.

- [ ] **Step 9: Commit the Providers tab implementation**

```bash
git add frontend/src/views/Analytics.vue frontend/src/views/Analytics.spec.ts
git commit -m "feat: add analytics providers tab"
```

---

### Task 6: Add Providers-tab i18n copy and finalize verification

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
- Test: `frontend/src/views/Analytics.spec.ts`

- [ ] **Step 1: Add English analytics keys**

Inside the `analytics` block in `frontend/src/i18n/messages/en.ts`, add:

```ts
overviewTab: 'Overview',
providersTab: 'Providers',
activeProviders: 'Active Providers',
providerCoveredTasks: 'Provider-covered Tasks',
providerCoveredTokens: 'Provider-covered Tokens',
providerSuccessRate: 'Provider Success Rate',
provider: 'Provider',
providersComparison: 'Provider Comparison',
providersComparisonSubtitle: 'Compare provider volume, quality, and efficiency under the current filters.',
providerSuccessRateChart: 'Success Rate by Provider',
providerSuccessRateChartSubtitle: 'Finished-task success rate for each provider.',
providerEfficiencyChart: 'Efficiency by Provider',
providerEfficiencyChartSubtitle: 'Switch between throughput and change-efficiency views.',
avgTokensPerSecond: 'Avg Tokens / Sec',
avgTokensPerChangedLine: 'Avg Tokens / Changed Line',
avgSecondsPerChangedLine: 'Avg Sec / Changed Line',
providersEmpty: 'No provider analytics match the current filters and time window yet.',
```

- [ ] **Step 2: Add matching Chinese keys**

Inside the `analytics` block in `frontend/src/i18n/messages/zh-CN.ts`, add:

```ts
overviewTab: '总览',
providersTab: 'Providers',
activeProviders: '活跃 Provider 数',
providerCoveredTasks: '纳入 Provider 统计的任务数',
providerCoveredTokens: '纳入 Provider 统计的 Tokens',
providerSuccessRate: 'Provider 成功率',
provider: 'Provider',
providersComparison: 'Provider 对比',
providersComparisonSubtitle: '在当前筛选条件下对比各 Provider 的任务量、质量与效率。',
providerSuccessRateChart: '各 Provider 成功率',
providerSuccessRateChartSubtitle: '按已结束任务口径统计的成功率。',
providerEfficiencyChart: '各 Provider 效率对比',
providerEfficiencyChartSubtitle: '在吞吐与变更效率指标之间切换查看。',
avgTokensPerSecond: '平均 Tokens / 秒',
avgTokensPerChangedLine: '平均 Tokens / 变更行',
avgSecondsPerChangedLine: '平均秒数 / 变更行',
providersEmpty: '当前筛选条件和时间窗口下还没有匹配的 Provider 统计数据。',
```

- [ ] **Step 3: Update the frontend test mock translations if needed**

In `frontend/src/views/Analytics.spec.ts`, extend the mocked `t()` dictionary so the provider empty-state assertion resolves to actual copy instead of the raw i18n key:

```ts
'analytics.providersEmpty': 'No provider analytics match the current filters and time window yet.',
```

- [ ] **Step 4: Run the frontend test suite**

Run: `make test-frontend`

Expected: PASS.

- [ ] **Step 5: Run the backend test suite**

Run: `make test-backend`

Expected: PASS.

- [ ] **Step 6: Run final build verification**

Run: `cd frontend && npm run build`

Expected: PASS.

- [ ] **Step 7: Commit the final polish**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts frontend/src/views/Analytics.spec.ts
git commit -m "feat: localize analytics provider insights"
```

---

## Scope Boundaries

Keep this implementation inside the approved v1 boundary:

- Extend the current `/api/stats/analytics` endpoint rather than creating a new API.
- Do not introduce ECharts.
- Do not add provider-specific filters.
- Do not add provider trend time-series charts.
- Do not add export, download, or cost analytics.
- Do not refactor unrelated Analytics sections while implementing this feature.

## Self-Review

- **Spec coverage:** The plan covers the approved v1 scope: top-level Providers tab, backend payload extension, provider summary/table/charts, shared filters, null-provider `Unknown / Legacy`, `N/A` handling for denominator-sensitive metrics, i18n, and verification.
- **Placeholder scan:** No TBD/TODO placeholders remain; every task includes exact files, code, and commands.
- **Type consistency:** The backend payload names (`provider_summary`, `providers`, `provider_chart_series`) match the spec and the frontend type/task names. The frontend plan uses the same metric keys end-to-end: `avg_tokens_per_second`, `avg_tokens_per_changed_line`, and `avg_execution_seconds_per_changed_line`.
