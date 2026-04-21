# Analytics Providers Tab V1 Design

## Summary

Add a new top-level `Providers` tab to the existing Analytics page so users can compare AI provider performance under the same global filters already used by the page. V1 focuses on provider-level task volume, token usage, success rate, and efficiency metrics without introducing a new charting library.

## Goals

- Let users compare AI providers in one place inside `Analytics.vue`.
- Reuse the existing analytics filters: time window, project, and initiator.
- Surface provider metrics that are useful for operational comparison, not just raw counts.
- Keep the implementation lightweight and consistent with the current Analytics page.
- Ship a maintainable v1 without turning Analytics into a full BI surface.

## Non-Goals

- No separate provider analytics page.
- No provider-specific secondary filters in v1.
- No provider trend time-series analysis in v1.
- No export/download flow.
- No percentile or p95 metrics.
- No cost/currency analytics.
- No ECharts introduction in v1.
- No migration of the rest of Analytics to a new charting system.

## Product Direction

The Analytics page should gain two top-level tabs:

- `Overview`
- `Providers`

`Overview` keeps the current analytics content. `Providers` presents aggregated provider comparison using the exact same filter state as the rest of the page.

This keeps provider analytics discoverable without fragmenting the information architecture or creating a parallel analytics screen.

## Why V1 Should Not Use ECharts

V1 should stay on the current lightweight chart/card approach already used in Analytics.

### Reasons

1. The provider views are simple comparison views, not advanced interactive visualizations.
2. Adding ECharts now would increase dependency, rendering, testing, and styling complexity.
3. Mixing two chart systems on one page would make Analytics harder to maintain.
4. The primary v1 value is in metric definition and provider comparison, not chart sophistication.

### Revisit Criteria

A charting-library migration can be reconsidered later if the page grows into:

- provider time-series trends
- multi-series comparisons
- dual-axis charts
- richer tooltips/legends/zoom
- cross-chart interaction

## UX Structure

### Top-Level Tabs

Add a top-level tab switch in `frontend/src/views/Analytics.vue`:

- `Overview` remains default
- `Providers` becomes the second tab

The existing controls for:

- window days
- project
- initiator
- refresh

remain shared and global above the tab content.

### Providers Tab Layout

The `Providers` tab should render, in order:

1. Provider summary cards
2. Provider comparison table
3. Provider comparison charts

This mirrors the existing Analytics structure of summary first, then deeper comparison views.

## Metrics to Show

### Summary Cards

The Providers tab should show four high-level summary cards:

- Active Providers
- Provider-covered Tasks
- Provider-covered Tokens
- Provider Success Rate

### Provider Comparison Table

Each provider row should show:

- Provider name
- Model name
- Tasks
- Success Rate
- Total Tokens
- Avg Tokens / Task
- Avg Tokens / Sec
- Avg Tokens / Changed Line
- Avg Sec / Changed Line

### Comparison Charts

V1 should include two chart cards:

1. **Success Rate by Provider**
2. **Efficiency by Provider**

The Efficiency card should support a small metric toggle between:

- Avg Tokens / Sec
- Avg Tokens / Changed Line
- Avg Sec / Changed Line

These are enough to answer the main product question: which providers are handling meaningful work, and how efficient are they when they do.

## Backend API Design

Extend the existing `GET /api/stats/analytics` response instead of creating a new endpoint.

### New Response Sections

Add:

- `provider_summary`
- `providers`
- `provider_chart_series`

### Provider Summary Shape

`provider_summary` should contain aggregate values for the Providers tab summary cards:

- `active_provider_count`
- `provider_covered_task_count`
- `provider_covered_total_tokens`
- `provider_success_rate`

### Provider Row Shape

Each item in `providers` should contain:

- `provider_id`
- `provider_name`
- `provider_model`
- `task_count`
- `finished_task_count`
- `completed_task_count`
- `failed_task_count`
- `cancelled_task_count`
- `success_rate`
- `total_input_tokens`
- `total_output_tokens`
- `total_tokens`
- `avg_tokens_per_task`
- `avg_tokens_per_second`
- `avg_tokens_per_changed_line`
- `avg_execution_seconds`
- `avg_execution_seconds_per_changed_line`

### Provider Chart Series Shape

`provider_chart_series` should be a frontend-friendly structure derived from the same provider rows, intended for the two Providers tab charts. It should avoid requiring the frontend to re-derive ranking and labels from scratch.

A simple shape is enough in v1:

- `success_rate`
- `avg_tokens_per_second`
- `avg_tokens_per_changed_line`
- `avg_execution_seconds_per_changed_line`

Each series can contain ordered rows with provider label and numeric value.

## Metric Definitions

Metric definitions need to be explicit so the table, charts, and tests all agree.

### Success Rate

`success_rate = completed_task_count / finished_task_count`

Where finished tasks are the subset of tasks with terminal outcome:

- completed
- failed
- cancelled

Pending, queued, and running tasks must not be counted in the denominator.

### Total Tokens

`total_tokens = total_input_tokens + total_output_tokens`

### Avg Tokens / Task

Average over provider tasks with token data present.

### Avg Tokens / Sec

Average over tasks where both of these are true:

- total token data exists
- execution duration exists and is greater than zero

Tasks that do not satisfy the denominator requirements must be excluded from this average.

### Avg Tokens / Changed Line

Average over tasks where both of these are true:

- total token data exists
- total changed lines is greater than zero

### Avg Execution Seconds

Average over tasks with valid execution duration.

### Avg Sec / Changed Line

Average over tasks where both of these are true:

- execution duration exists
- total changed lines is greater than zero

### Missing-Denominator Rule

When a metric cannot be computed for a provider because no tasks satisfy its denominator rules, the backend should return `null` for that metric rather than `0`.

This prevents the UI from implying a measured zero when the real state is insufficient data.

## Filter Semantics

Provider analytics must use the exact same filters as the rest of `/api/stats/analytics`:

- time window
- project
- initiator
- access scope

This means the Providers tab is another view of the same filtered analytics universe, not a separate data source.

## Unknown / Legacy Provider Bucket

Tasks with `provider_id = null` should be grouped into a synthetic provider bucket:

- `provider_id = null`
- `provider_name = "Unknown / Legacy"`
- `provider_model = null`

This ensures older tasks and tasks created before provider tracking are still visible in provider analytics instead of disappearing from the comparison surface.

## Frontend Rendering Rules

### Default Behavior

- The page opens on `Overview`.
- The Providers tab only renders when analytics data has loaded.
- Shared filters and refresh behavior remain unchanged.

### Provider Labels

Show provider name and model together when model exists.

Examples:

- `Claude Sonnet / claude-sonnet-4-6`
- `Unknown / Legacy`

### Sorting

Default table sort should be by `task_count` descending.

### N/A Rendering

If a provider metric is `null`, render `N/A` in the table and omit it from the corresponding chart series.

### Large Provider Counts

If there are many providers, the charts may limit to top-N providers for readability, using task count as the default ranking basis.

The full table should still show all provider rows.

### Empty State

If no provider rows are available under the current filters, render a dedicated Providers-tab empty state instead of blank charts/tables.

The empty state should explain that no provider analytics match the current filters and time window.

## Affected Files

### Backend

- `backend/app/api/stats.py`
- `backend/tests/unit/test_task_analytics_api.py`

### Frontend

- `frontend/src/views/Analytics.vue`
- `frontend/src/views/Analytics.spec.ts`
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`

## Testing Strategy

### Backend Unit Tests

Extend provider-related coverage in `backend/tests/unit/test_task_analytics_api.py` to verify:

- response contains `provider_summary`, `providers`, and `provider_chart_series`
- grouping by provider works correctly
- `Unknown / Legacy` bucket captures `provider_id = null`
- success rate denominator only uses finished tasks
- denominator-sensitive metrics return `null` when not computable
- project/initiator/window filters affect provider analytics consistently

### Frontend Unit Tests

Extend `frontend/src/views/Analytics.spec.ts` to verify:

- default tab remains `Overview`
- switching to `Providers` renders provider cards/table/charts
- provider empty state appears when no provider analytics data exists
- `N/A` is rendered for null metrics
- efficiency metric toggle updates only the intended chart card state
- shared filters still drive the rendered provider analytics content

### Verification Commands

Minimum verification for implementation:

- `make test-backend`
- `make test-frontend`

If the frontend data shape changes materially, also run:

- `npm run build`

## Risks and Mitigations

### Risk: metrics are misunderstood because denominators differ
Mitigation: define formulas explicitly in backend implementation and render `N/A` rather than fake zeros.

### Risk: provider analytics duplicates Overview too much
Mitigation: keep Providers focused on provider comparison and efficiency, not on repeating every overview metric.

### Risk: too many providers make charts unreadable
Mitigation: allow chart series to limit to top-N while preserving the full table.

### Risk: adding ECharts would bloat this change
Mitigation: keep v1 on the existing lightweight chart approach and defer chart-library changes until there is a stronger need.

## Scope Check

This is a focused Analytics enhancement. It extends the current analytics endpoint and page rather than introducing a new analytics subsystem. The scope is intentionally limited to provider comparison in a single tab so it can be implemented as one coherent feature.
