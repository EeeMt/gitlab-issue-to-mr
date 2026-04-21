# Analytics Status Cards Placement and Empty State Design

## Summary

Refine the new Analytics issue/task status distribution cards so they appear earlier in the page hierarchy and handle empty datasets explicitly. The two status cards should move to immediately after the summary cards and before all trend charts. When a card has no data in the current filter window, it should render a whole-card empty state instead of an empty bar/donut visualization.

## Goals

- Make issue/task status distribution easier to discover by moving the cards earlier in the Analytics page.
- Keep the new status cards grouped together as a single high-level section after the summary cards.
- Make zero-data states explicit and readable instead of showing empty visualizations.
- Preserve the existing independent bar/donut toggle behavior for each card.

## Non-Goals

- No changes to analytics API shape or filter semantics.
- No redesign of the summary cards, trend cards, or breakdown table behavior.
- No new chart type beyond the existing bar and donut views.
- No generic empty-state component extraction for this small scope.

## Design Direction

### Placement

The status distribution section should move to:

`summary cards -> status distribution cards -> trend charts -> breakdown / tables`

This keeps the page ordered from high-level totals, to high-level state distribution, to time-series trends, and finally to detailed tables.

The two status cards should remain side-by-side on desktop and stacked on mobile, using the existing analytics card grid behavior.

### Empty state behavior

Each card should compute its own total:

- issue card uses `issueStatusTotal`
- task card uses `taskStatusTotal`

If a card total is `0`, do not render the bar or donut content area. Instead, render a compact whole-card empty state in the card body.

Requirements for the empty state:

- keep the card header, title, subtitle, and chart-mode toggle visible
- replace the chart body with a short placeholder message
- make the empty state read as intentional, not as broken or unfinished UI
- use lightweight styling aligned with the existing analytics cards

The chart-mode toggle should remain visible even in the empty state so the control layout stays stable, but switching modes should not change the empty-state body while total remains `0`.

### Copy

Add explicit analytics empty-state copy for both cards:

- issue status distribution empty message
- task status distribution empty message

The wording should describe that there is no matching data under the current filters / time window, rather than implying a loading or error condition.

## Affected Files

- `frontend/src/views/Analytics.vue`
- `frontend/src/views/Analytics.spec.ts`
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`

## Testing

Update the focused analytics view tests to cover:

- status cards render before the trend chart section
- each card shows an empty-state message when its total is `0`
- bar/donut chart rendering still appears when data exists
- independent chart-mode switching remains intact

Frontend build should continue to pass after the layout reorder and empty-state changes.

## Risks and Mitigations

### Risk: section reorder makes page feel too dense near the top
Mitigation: keep the status cards in the existing two-column card grid and avoid adding extra explanatory chrome.

### Risk: empty state feels visually dead
Mitigation: use concise placeholder copy and centered, low-noise styling so the card still feels deliberate and complete.

### Risk: toggle controls look confusing when no data exists
Mitigation: keep controls visible for layout stability, but make the empty-state copy clearly explain that current filters have no matching data.

## Scope Check

This is a small follow-up polish task on the already-added analytics status cards. It is limited to page ordering and empty-state handling and remains small enough for one focused implementation change.
