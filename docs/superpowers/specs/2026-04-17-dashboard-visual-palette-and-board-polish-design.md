# Dashboard Visual Palette and Board Lane Polish Design

## Summary

Refresh the dashboard’s visual language so the chart colors feel more aligned with the product, and add light visual polish to the My Work Board. The dashboard should move from brighter status-oriented chart colors to a cooler product palette, while the board gains lane icons and lighter task prompt typography.

## Goals

- Make dashboard pie charts feel visually consistent with the rest of the application.
- Make trend line colors feel product-aligned rather than generic monitoring colors.
- Improve scanability of My Work Board lanes by adding a small icon to each lane title.
- Reduce the visual heaviness of task prompt text in kanban cards.
- Keep the changes lightweight and styling-focused.

## Non-Goals

- No lane reordering or lane behavior changes.
- No changes to board data fetching or grouping.
- No changes to task or issue list filter/badge colors outside the dashboard visualizations.
- No full theme-system rewrite.
- No board background or card layout redesign.

## Design Direction

### Dashboard chart palette

Adopt a cooler product-style palette for dashboard charts.

The current dashboard mixes strong semantic colors like orange/green/blue in a way that reads more like a generic operational console than the rest of the product UI. The new palette should shift the charts toward a calmer, more cohesive family built around slate, sky, teal, and violet tones.

Guiding color roles:
- neutral/base: slate
- primary: sky blue
- secondary: teal
- accent: violet

This direction should apply to:
- issue status pie chart color mapping in `frontend/src/views/Dashboard.vue`
- task status pie chart color mapping in `frontend/src/views/Dashboard.vue`
- trend series and point colors in `frontend/src/components/TrendChart.vue`

The exact hex values should be chosen to preserve contrast and chart legibility on the existing light dashboard cards.

### Trend chart polish

`TrendChart.vue` should use the same cooler palette family across its visible series.

If the updated series colors make existing axis or grid colors feel too warm or too muted by comparison, lightly tune those neutrals so the chart still feels balanced. Keep these adjustments subtle; the main change is the series palette, not a chart redesign.

## My Work Board polish

### Lane title icons

Add a small icon to each lane title in `frontend/src/components/dashboard/MyWorkBoard.vue`.

Requirements:
- Each lane header should show an icon before the text label.
- Icons should be small, visually quiet, and consistent across issue and task lanes.
- Icons should improve scanability without making the board noisy.
- The icon treatment should work for both issue and task tabs.

Implementation direction:
- Add a status-to-icon mapping in `MyWorkBoard.vue` or a nearby lightweight structure used only by that component.
- Do not add a new abstraction layer or a shared design system utility for this one component.
- Prefer the same icon family already used elsewhere in the dashboard.

### Task prompt typography

Make the task prompt/title text lighter in visual weight in `frontend/src/components/dashboard/MyWorkBoard.vue`.

Requirements:
- Task card prompt text should feel less heavy than it does now.
- The text should remain readable and still be the primary card content.
- Issue cards do not need to change unless required for consistency during implementation.

Implementation direction:
- Prefer a smaller typography-only adjustment such as reducing `font-weight` or slightly tuning color, rather than changing spacing or card structure.
- Keep the existing multi-line truncation behavior.

## Affected Files

- `frontend/src/views/Dashboard.vue`
- `frontend/src/components/TrendChart.vue`
- `frontend/src/components/dashboard/MyWorkBoard.vue`
- `frontend/src/views/Dashboard.spec.ts`

## Testing

Update or extend `frontend/src/views/Dashboard.spec.ts` only where needed for the board UI changes.

Expected verification:
- My Work Board still renders both issue and task lanes correctly.
- Lane headers still render expected labels after icons are introduced.
- Task card prompt content still renders and preserves truncation behavior.
- Existing dashboard tests continue to pass after chart color changes.

No visual snapshot testing is required for this scope.

## Risks and Mitigations

### Risk: cooler palette weakens semantic meaning
Mitigation: keep relative contrast between categories clear, even if the hues shift away from traffic-light colors.

### Risk: icons create header clutter
Mitigation: use small low-emphasis icons and keep spacing tight.

### Risk: lighter task typography reduces readability
Mitigation: adjust weight conservatively and preserve contrast against the current card background.

## Scope Check

This remains a single focused UI polish task covering:
- dashboard chart palette alignment
- board lane header icons
- task prompt typography tuning

It is still small enough for one implementation plan and one frontend change set.
