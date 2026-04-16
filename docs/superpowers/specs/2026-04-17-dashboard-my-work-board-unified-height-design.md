# Dashboard My Work Board Unified Tab Height Design

## Summary

Keep the `Dashboard` page unchanged and adjust `frontend/src/components/dashboard/MyWorkBoard.vue` so the Issues and Tasks tabs always render within the same fixed board panel height. The content area below the tab buttons will reserve a shared height for both tabs, and all tab-specific content — limit notice, empty state, and status columns — will render inside that shared panel.

## Problem

The current board allows each tab to size itself based on its own content. In practice, the Tasks tab can show a limit notice while the Issues tab may not, and either tab can have different empty/content distributions. That causes the visible board height to jump when switching tabs.

## Goals

- Keep Issues and Tasks tabs at the same overall panel height.
- Prevent visible layout jumping when switching tabs.
- Preserve the current card, notice, empty state, and column behaviors.
- Keep the change CSS-first and easy to maintain.

## Non-Goals

- No dynamic JS measurement between tabs.
- No backend or API changes.
- No pagination or “load more” behavior changes.
- No redesign of board columns or card content.

## Recommended Approach

Use one shared fixed/min-height board content container inside `MyWorkBoard.vue`.

### Structure

Inside the card:
- tab buttons remain at the top
- add a shared content wrapper below tabs
- render the notice, empty state, or columns inside that wrapper

### Layout behavior

- The shared content wrapper gets a fixed or minimum height that applies to both tabs.
- When a notice is present, it consumes space inside the shared wrapper instead of increasing the outer board height.
- When a tab is empty, the empty state renders inside the same wrapper and does not collapse the panel.
- When columns are shown, the columns area stretches to fill the remaining wrapper height.
- Each column body keeps internal scrolling so long lists remain usable without changing overall tab height.

## Component Changes

### `frontend/src/components/dashboard/MyWorkBoard.vue`

Add a dedicated board panel container, for example:
- `.my-work-board__panel`
- `.my-work-board__panel-content`

Expected CSS behavior:
- panel uses a shared `min-height` or `height`
- panel layout uses flex column
- notice and empty state live inside the panel
- columns container uses `flex: 1` or equivalent so it fills available panel space
- column body keeps its internal scroll behavior

Recommended implementation style:
- keep the current template logic mostly intact
- avoid JS-based height measurement
- prefer a single explicit panel height value in component styles

## Testing

Update `frontend/src/views/Dashboard.spec.ts` with focused assertions that confirm:
- the board still renders correctly on both tabs
- the shared panel container exists
- switching between issues and tasks does not depend on tab-specific outer wrappers
- current notice/empty-state tests continue to pass after the structural change

This should remain a lightweight unit-test adjustment rather than visual snapshot testing.

## Risks and Mitigations

### Risk: Too much empty space on sparse tabs
This is acceptable because stable layout is the primary goal.

### Risk: Nested scroll feels awkward
Mitigation: keep scrolling limited to column bodies, not the full card or page.

### Risk: Notice plus columns reduce visible item space
Mitigation: this is still preferable to changing total board height between tabs.

## Implementation Scope

Single-file UI change plus small test adjustment:
- `frontend/src/components/dashboard/MyWorkBoard.vue`
- `frontend/src/views/Dashboard.spec.ts`

No plan decomposition is needed; this is appropriately scoped for one small implementation task.
