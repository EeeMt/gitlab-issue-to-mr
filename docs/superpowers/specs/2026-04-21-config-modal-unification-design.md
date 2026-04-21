# Config Page CRUD Editors → Unified Modal Design

## Problem Statement

The Config page currently uses three different create/edit patterns for similar CRUD-style entities:

- **AI Providers** use a right-side drawer
- **Prompt Templates** use an inline editor inside the card
- **Mattermost Notification Profiles** already use a modal

This makes the page feel inconsistent. Users must relearn the editing flow depending on which tab they are in, and the Prompt Template inline editor also expands the page vertically in a way the other panels do not.

## Goal

Unify the **add/edit** experience for:

- AI providers
- Prompt templates
- Mattermost notification profiles

All three should use a consistent **`n-modal`-based** interaction model on both desktop and mobile.

## Scope

### In Scope

- Convert AI Provider create/edit from drawer to modal
- Convert Prompt Template create/edit from inline editor to modal
- Align Mattermost Notification Profile modal behavior with the same modal conventions
- Keep existing APIs, validation, and data flow intact
- Update frontend tests affected by the interaction change

### Out of Scope

- Backend API changes
- New shared CRUD framework
- Refactoring unrelated Config tabs
- Changing delete / set-default / test-connection flows

## Chosen Approach

Use **panel-local modal implementations** rather than introducing a new shared abstraction.

Each panel will keep its own form state, validation rules, save handlers, and fetch logic. The change is limited to replacing inconsistent edit surfaces with a consistent modal shell and matching interaction rules.

### Why this approach

- Lowest risk for an existing page with multiple mature panels
- Keeps current business logic and validation untouched
- Achieves the UX goal without expanding scope into framework work
- Leaves room to extract a shared modal wrapper later if repetition becomes painful

## Current State

| Area | Current editor pattern | Target editor pattern |
|------|------------------------|-----------------------|
| AI Providers | `n-drawer` | `n-modal` |
| Prompt Templates | Inline editor block inside card | `n-modal` |
| Mattermost Notification Profiles | `n-modal` | Keep `n-modal`, align behavior |

## Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Modal primitive | `n-modal` with `preset="card"` | Matches existing Mattermost profile editor and gives a consistent shell |
| Mobile behavior | Still use modal | User explicitly wants desktop and mobile unified |
| Shared abstraction | Not in this change | Avoid over-refactoring a focused UX task |
| Form ownership | Remains inside each panel | Preserves existing validation and API logic |
| Save lifecycle | Validate → save → success message → close modal → refresh list | Consistent behavior across all three editors |
| Cancel/close lifecycle | Close modal and reset transient editor state | Prevent stale form state from leaking between sessions |

## UX Design

### Shared interaction contract

All three editors will follow the same interaction model:

1. User clicks **Create** or **Edit**
2. A modal opens with the relevant form prefilled or reset
3. User clicks **Save**
4. The panel validates using its existing rules
5. On success:
   - show success toast
   - close modal
   - refresh the list/table
6. On cancel or close:
   - dismiss modal
   - clear transient form state used for that editing session

### Modal sizing

- **Mobile:** `96vw`
- **Desktop:** fixed widths chosen per form complexity
  - AI Providers: medium-width modal
  - Prompt Templates: wider modal to fit `VariableEditor`
  - Mattermost Notification Profiles: keep current wide modal size unless minor alignment tweaks are needed

Exact widths can follow the current Mattermost style and remain implementation detail, but the intent is:

- AI Provider modal should feel compact
- Prompt Template and Mattermost modals should have enough room for multi-section forms

### Footer actions

Each modal uses the same footer hierarchy:

- Secondary **Cancel**
- Primary **Save**

Button ordering and loading states should be visually consistent across the three panels.

## Component-Level Changes

### 1. `frontend/src/components/config/AIProvidersPanel.vue`

Replace the current drawer-based editor with a modal-based editor.

#### Keep unchanged

- providers table
- create/edit/delete/set-default actions
- existing field structure
- current validation rules
- current API calls

#### Change

- Replace:
  - `drawerVisible`
  - `<n-drawer>`
  - `<n-drawer-content>`
- With:
  - `modalVisible`
  - `<n-modal preset="card">`

The create/edit handlers (`openCreate`, `openEdit`, `handleSave`) should remain structurally the same, with only modal visibility and close/reset behavior adjusted.

### 2. `frontend/src/views/config/PromptTemplatesPanel.vue`

Move the editor out of the card body into a modal.

#### Keep unchanged

- template table and mobile list
- create/edit/delete actions
- `VariableEditor`
- variable tips validation logic
- create/update API payloads

#### Change

- Remove the inline `prompt-template-editor` block from the card body
- Introduce a modal controlled by the existing create/edit actions
- Render the full prompt template form inside the modal

This makes Prompt Templates consistent with the other tabs and prevents the inline editor from pushing the rest of the page downward.

### 3. `frontend/src/components/config/MattermostNotificationsPanel.vue`

Mattermost notification profiles already use a modal. The goal here is not structural change, but consistency.

#### Keep unchanged

- integration settings form
- profile list
- create/edit/delete profile APIs
- validation rules

#### Align if needed

- modal title styling
- footer button ordering
- width conventions
- close/reset behavior

The integration form itself remains inline because the request only targets **profile add/edit**, not the Mattermost connection settings section.

## Data Flow

No backend or API contract changes are needed.

Each panel keeps its existing local state:

- list loading state
- save loading state
- editing entity id/reference
- form model
- form ref

This means the modal change is presentation-level, not architectural.

### Save flow

Each panel continues to:

1. validate the current form
2. choose `create` vs `update` based on edit state
3. call the existing API
4. show feedback with `useMessage`
5. refresh panel data

### Reset flow

Each panel should explicitly reset its editor state when:

- opening create mode
- closing the modal after cancel
- finishing a successful save

This avoids stale data from the previous editing session.

## Validation and Error Handling

Validation behavior stays exactly where it is today.

- **AI Providers**
  - name required and format-constrained
  - base URL required and must be http/https
  - model required
  - max turns bounded

- **Prompt Templates**
  - name/content remain required in practice
  - variable tips must match variables present in the template content

- **Mattermost Profiles**
  - profile name required
  - target-specific team/channel validation
  - event selection required
  - field selection required

### Error handling

- Keep existing API error handling and fallback messages
- Do not swallow validation failures
- Do not add silent resets on failed save

## Testing

Frontend tests should be updated to reflect the interaction change rather than rewritten from scratch.

### AI Providers

- Cover opening create modal
- Cover opening edit modal with prefilled values
- Cover save success closing the modal

### Prompt Templates

- Replace assertions that depend on inline editor rendering
- Cover create/edit opening the modal
- Cover save/cancel behavior in modal mode
- Keep existing variable-tip validation coverage

### Mattermost Profiles

- Only adjust tests if needed for unified modal conventions
- No broad rewrite expected

### Verification

- relevant frontend unit tests for touched panels
- Config page tests if interaction expectations change there
- `npm run build`

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Prompt Template tests are tightly coupled to inline markup | Update tests to target modal state and existing create/edit handlers |
| Mobile modal layout becomes cramped | Use wide mobile modal (`96vw`) and keep current section grouping |
| Hidden stale form state after modal close | Explicit reset on cancel and after successful save |
| Scope creep into shared abstractions | Keep implementation panel-local for this change |

## Implementation Notes

- Reuse existing i18n keys where possible
- Only add new copy if the modal UI truly needs it
- Preserve current tab structure and route query behavior in `Config.vue`
- Keep changes surgical: only the three requested create/edit surfaces should change
