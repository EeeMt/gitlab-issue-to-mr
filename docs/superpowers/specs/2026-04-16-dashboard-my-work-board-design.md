# Dashboard My Work Board Design

## Overview

Replace the `Recent Issues` and `Running` sections on the dashboard with a single unified **My Work Board** that shows the current user's issues or tasks in a kanban-style layout. The board uses tabs to switch between `Issues` and `Tasks`, defaults to `Issues`, and groups cards by status.

This board is read-only. It is intended to give the current user a quick dashboard-level view of their work distribution and direct navigation into issue/task detail pages.

## Goals

- Replace the two existing dashboard table sections with a single board-oriented view.
- Show only the current user's issues and tasks.
- Use tabs to switch between `Issues` and `Tasks`.
- Present records in status columns rather than tables.
- Keep the dashboard height controlled by limiting each column to a 5-card visible area with internal scrolling.
- Preserve fast navigation to details by making each card clickable.

## Non-Goals

- Drag-and-drop status changes
- Inline editing from the dashboard
- Extra filtering or sorting controls inside the board
- Persisting the last selected tab
- User-configurable default tab
- Pagination or "view more" interactions inside the board

## Placement and Information Architecture

The dashboard keeps its existing summary cards and analytics/chart sections unchanged.

The following existing sections are removed from `Dashboard.vue`:
- `Recent Issues`
- `Running`

They are replaced by a single new section:
- `My Work Board`

The board contains:
- A header/title for the board
- Tabs for `Issues` and `Tasks`
- A kanban-style set of status columns for the selected tab

Default tab:
- `Issues`

## Status Model

### Issues tab

The Issues view always renders these columns in this order:
1. `open`
2. `in_progress`
3. `in_review`
4. `closed`

### Tasks tab

The Tasks view always renders these columns in this order:
1. `pending`
2. `queued`
3. `running`
4. `completed`
5. `failed`
6. `cancelled`

Columns remain visible even when empty so the overall state model stays stable and easy to scan.

## Component Design

Create a new presentation-focused component:
- `frontend/src/components/dashboard/MyWorkBoard.vue`

### Responsibilities of `Dashboard.vue`

`Dashboard.vue` remains the page-level orchestrator. It is responsible for:
- Fetching the current user's issue data
- Fetching the current user's task data
- Grouping those records by status into board-ready structures
- Passing structured props into `MyWorkBoard.vue`
- Continuing to own page-level loading and refresh behavior
- Reusing the existing router navigation patterns

### Responsibilities of `MyWorkBoard.vue`

`MyWorkBoard.vue` is a display and interaction component. It is responsible for:
- Rendering the board shell
- Rendering the `Issues / Tasks` tabs
- Rendering status columns for the active tab
- Rendering cards inside each status column
- Showing empty states for empty columns or empty tabs
- Enforcing the visual 5-card visible height with internal column scroll
- Emitting or handling card click navigation behavior

### Data Contract

`MyWorkBoard.vue` should not fetch its own data.

`Dashboard.vue` should pass pre-grouped props shaped conceptually like:
- `issueColumns: Array<{ status, label, count, items }>`
- `taskColumns: Array<{ status, label, count, items }>`

This keeps the board component focused on rendering and prevents API concerns from leaking into presentation logic.

## Data Fetching Strategy

The current dashboard already filters by current user:
- issues via `initiator_user_id`
- tasks via `initiator_username`

The new board expands the fetched scope beyond the current implementation:
- Issues: fetch enough current-user issue records to populate all four statuses
- Tasks: fetch enough current-user task records to populate all six statuses

The dashboard should no longer fetch only:
- the latest 5 issues
- running tasks
- queued tasks

Instead, it should fetch board-oriented datasets and group them locally by status.

Implementation should follow existing frontend API usage patterns. If pagination limits are required by the API, the first implementation should choose a practical capped page size that is sufficient for dashboard display, while keeping scope limited to the current dashboard experience.

## Card Content

### Issue card fields

Each issue card should show:
- title
- `#id`
- project label
- task count
- created time

Do not include secondary dashboard-heavy metadata such as MR links, token usage, or code change totals on issue cards.

### Task card fields

Each task card should show:
- prompt summary derived from `user_prompt`
- `#id`
- project label
- priority
- time label

Time label rule:
- use `started_at` when present
- otherwise fall back to `created_at`

Do not include extra task metadata such as token counts, change counts, or provider details in the first version.

## Interaction Design

- The board defaults to the `Issues` tab.
- Switching tabs updates the visible set of columns without a route change.
- Clicking an issue card navigates to `/issues/:id`.
- Clicking a task card navigates to `/tasks/:id`.
- The board is read-only; no drag handles, action menus, or status mutation controls are included.

## Layout and Responsive Behavior

### Desktop

- Render the board as horizontally arranged status columns.
- Each column should have a stable minimum width suitable for card scanning.
- Columns should visually read as a kanban board.
- Column headers should display the localized status label and item count.

### Mobile

- Render columns in a vertical stacked layout rather than forcing a compressed multi-column grid.
- Preserve the same status ordering used on desktop.
- Keep the card design concise to avoid excessive vertical bloat.

## Scrolling and Height Behavior

Each status column should preserve a controlled height.

Design rule:
- show a visible area roughly equivalent to 5 cards
- if more items exist in a column, the column itself scrolls internally

This prevents the new board from making the dashboard excessively tall while still exposing all statuses.

Columns in the active board should align to the same visual height on desktop.

## Empty States

### Empty column

If a specific status has no items:
- keep the column visible
- show the column header normally
- show a short empty-state message inside the column

### Empty tab

If the selected tab has no items at all:
- show a board-level empty state for that tab
- do not hide the tabs or overall board shell

This preserves structure and makes it clear that the absence of data is meaningful, not a rendering failure.

## Loading and Error Behavior

The board should follow existing dashboard loading/error conventions.

- The dashboard page continues to own loading states.
- The board should render from the prepared data it receives.
- If the board data request fails, use the existing dashboard error handling pattern instead of adding a separate custom error surface inside the component.
- Supplementary dashboard sections should remain unaffected by the board layout change.

## Localization

Add localized strings in:
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`

Expected additions include:
- board title
- tab labels (`Issues`, `Tasks`)
- empty-state text
- any card field labels not already covered by existing shared strings

Prefer reusing existing status and common labels wherever possible to keep terminology consistent.

## Testing Strategy

Add or update frontend unit tests to verify:

1. Dashboard renders the new board instead of the removed `Recent Issues` and `Running` sections.
2. The default active tab is `Issues`.
3. Switching to `Tasks` shows the task status columns.
4. Issue records are grouped into the correct issue status columns.
5. Task records are grouped into the correct task status columns.
6. Empty columns still render their headers and empty-state message.
7. Empty tabs render a board-level empty state.
8. Clicking an issue card navigates to the matching issue detail route.
9. Clicking a task card navigates to the matching task detail route.
10. New i18n strings are wired correctly for both English and Simplified Chinese.

## Files Expected to Change

Primary files:
- `frontend/src/views/Dashboard.vue`
- `frontend/src/components/dashboard/MyWorkBoard.vue`
- `frontend/src/i18n/messages/en.ts`
- `frontend/src/i18n/messages/zh-CN.ts`
- dashboard-related frontend test files

## Open Decisions Resolved

The following decisions are now fixed for implementation:
- Replace the existing `Recent Issues` and `Running` blocks
- Use a dedicated component approach rather than embedding all board rendering in `Dashboard.vue`
- Use a unified board with tabs
- Default to `Issues`
- Use read-only cards with detail-page navigation
- Show 5-card visible height per column with internal scroll

## Summary

The dashboard will gain a focused, user-specific board experience that better matches the requested kanban mental model than the current pair of tables. The design keeps page-level data orchestration in `Dashboard.vue`, moves board presentation into a dedicated component, and limits scope to a clean first version with strong testability and minimal behavioral risk.
