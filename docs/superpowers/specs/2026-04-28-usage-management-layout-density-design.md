# Usage Management Layout Density Design

## Summary

Tighten the Usage Management page so each user's information is easier to scan without feeling scattered. The page should keep the current card-based interaction model, but reframe each user row as a denser admin card that follows the visual grouping used in Access Management.

## Goals

- Make each user card noticeably denser and easier to scan.
- Reuse the layout language already established in `AccessManagement.vue`.
- Keep the existing search and save flows intact.
- Preserve mobile readability while reducing vertical sprawl on desktop.

## Non-Goals

- No API or quota-behavior changes.
- No switch to a table-first layout.
- No change to the system-default limits card beyond small consistency cleanup if needed.

## Design Direction

### Overall page structure

Keep the existing page sections:

`summary cards -> system defaults -> user overrides`

The main layout change is inside each user override card.

### User card structure

Each user card should adopt the same information rhythm as Access Management:

1. **Top section**
   - Primary identity line with display name / username
   - Secondary metadata line for `@username`
   - Compact reset information shown near the header instead of as separate full-width rows

2. **Usage stats section**
   - Replace the current loose list of usage rows with a compact 2-column stat grid
   - Each stat block shows:
     - metric label
     - current usage
     - effective limit
   - Use one block each for:
     - daily tokens
     - weekly tokens
     - daily tasks
     - weekly tasks

3. **Edit section**
   - Keep the existing per-metric select + input controls
   - Present them as a tighter 2-column edit grid beneath the stats block
   - Save action remains at the bottom-right

### Density and spacing

- Reduce header-to-content spacing and card internal padding where possible.
- Replace repeated full-width rows with grouped stat/detail blocks.
- Keep labels visually muted and values more prominent, matching Access Management's stat styling.
- Reuse existing rounded-card treatment so the page still feels consistent with the rest of the admin area.

### Responsive behavior

- **Desktop:** identity + reset summary at the top, compact 2x2 stats grid, 2-column edit grid.
- **Mobile:** collapse the top area into a single column, keep stats as a single-column stack if needed, and keep edit controls full width.

## Affected Files

- `frontend/src/views/UsageManagement.vue`
- `frontend/src/views/UsageManagement.spec.ts`

## Testing

Update focused Usage Management tests to verify:

- user cards render the new compact grouped sections
- reset timestamps still render
- usage values and effective limit values still render
- existing save flows continue to work

Frontend build should continue to pass after the layout update.

## Risks and Mitigations

### Risk: denser layout becomes harder to parse
Mitigation: preserve clear section boundaries (identity, stats, edit controls) and use muted labels with emphasized values.

### Risk: mobile layout becomes cramped
Mitigation: allow the top area and stats/edit grids to stack cleanly on narrow screens instead of forcing fixed columns.

## Scope Check

This is a focused visual polish task on an existing page. It stays within one frontend view plus its tests and does not require backend or routing changes.
