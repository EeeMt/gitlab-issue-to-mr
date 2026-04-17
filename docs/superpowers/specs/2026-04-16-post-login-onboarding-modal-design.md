# Post-login onboarding modal design

## Summary
Design a first-login onboarding modal for Codify that introduces the product, explains its core concepts, and shows the end-to-end workflow. The modal should reflect the current product model where **Codify Issue** is the workflow starting point, not GitLab Issue-triggered execution.

## Goals
- Welcome new users and explain what Codify is for in a few seconds.
- Build a correct mental model for the main domain objects: Issue, Task, Worker, and Merge Request.
- Show how work moves from a Codify Issue to code output.
- Give users clear next actions after onboarding.

## Non-goals
- Detailed training for every page or feature.
- Configuration, provider, or auth setup explanation.
- GitLab Issue-triggered workflow education.
- Deep technical architecture or implementation details.

## User problem
After login, users can reach the main shell and see pages such as Dashboard, Issues, Tasks, and Configuration, but they may not understand:
- what Codify does overall
- what the main objects mean
- how those objects relate to each other
- what they should do first

The modal should reduce first-use confusion without overwhelming users.

## Core product framing
The onboarding must describe the current product truth:
- **Codify Issue** is the starting point of the workflow.
- A **Task** is created from an Issue to execute work.
- A **Worker** performs the execution in an isolated environment.
- A **Merge Request** is the result surface for code review and collaboration.
- GitLab Issue-based triggering is no longer part of the active product flow and must not appear in onboarding copy or diagrams.

## Delivery format
- A single large modal shown after login.
- Three steps inside the same modal.
- Clear step progress at the top.
- Navigation controls at the bottom.
- Final step includes two action buttons.

## Interaction model
### Trigger
- Show after successful login when the user enters the main application.
- Intended primarily for first-time onboarding.
- Future implementation can decide the exact persistence mechanism, but the UX intent is: do not repeatedly interrupt returning users after they have completed or skipped it.

### Controls
- Close icon in the top-right.
- "Skip introduction" action.
- "Previous" and "Next" between steps.
- Final-step CTAs:
  - "View Dashboard"
  - "Create Issue"

### Modal sizing
- Large centered modal.
- Target width around 880–980px on desktop.
- On smaller screens, content should stack and flow vertically rather than preserving desktop side-by-side layouts.

## Information architecture
### Step 1 — Welcome
Purpose: explain what Codify is and why the user should care.

#### Content
- Title: "欢迎使用 Codify" / localized equivalent
- Subtitle: a concise explanation that Codify starts from Codify Issues and moves work toward executable tasks, code changes, and Merge Requests.
- Three short value points:
  - use Issues to organize development goals
  - use Tasks to track execution and outcomes
  - turn results into branches and Merge Requests

#### Visual
A simple hero diagram showing:
- Codify Issue → Task → AI Worker → Branch / Merge Request

#### Content rule
Do not overload this step with definitions. It should establish confidence and product purpose.

### Step 2 — Core concepts
Purpose: build the user’s mental model.

#### Content
Top relationship diagram:
- Issue → Task → Worker → Branch / Merge Request

Below the diagram, four concept cards:
- **Issue**: Codify’s internal requirement object and the workflow starting point.
- **Task**: an execution unit created around an Issue, carrying prompt, status, and result.
- **Worker**: the execution unit that performs code generation and related workflow steps in an isolated environment.
- **Merge Request**: the review surface for the generated code output.

Supporting sentence:
- "Issue defines the goal, Task drives execution, Worker performs the work, and MR carries the result."

#### Content rule
Explain what each object is and how it relates to the others. Avoid implementation-heavy details.

### Step 3 — Workflow
Purpose: show how the system works end to end and what the user can do next.

#### Content
Five-step workflow:
1. Create Issue — create a Codify Issue with background, objective, and expected result.
2. Generate Task — create a Task from that Issue and fill in execution prompt/parameters.
3. Enter scheduling — Scheduler arranges execution by queue and priority.
4. Execute generation — Worker runs in an isolated environment, generates code, commits a branch, and records progress.
5. Produce result — system creates a Merge Request for review and follow-up collaboration.

Ending copy:
- The user now understands the system’s concepts and flow.
- Offer two clear next actions: view the system overview or create a new Issue.

#### CTAs
- View Dashboard
- Create Issue

## Layout recommendations
### Shared modal layout
- Header: title, step progress, close action
- Body: current step content
- Footer: navigation controls or final CTAs

### Step 1 layout
- Desktop: two-column layout
  - left: hero illustration
  - right: title, subtitle, three value points
- Mobile: illustration above text

### Step 2 layout
- Recommended: relationship diagram on top, 2x2 concept cards below
- Mobile: vertical diagram or stacked cards

### Step 3 layout
- Desktop: horizontal process diagram or compact timeline
- Mobile: vertical timeline
- Bottom area: two CTAs with clear visual priority

## Visual style
- Product-oriented, clean, and lightweight.
- Professional rather than playful.
- Consistent with the current UI language in the app shell, login, and bootstrap screens.
- Prefer simple icons, soft gradients, arrows, and cards.
- Avoid dense architecture visuals or cartoon-heavy illustration.

## Tone of copy
- Clear and professional.
- Product-facing, not implementation-facing.
- Avoid outdated GitLab-trigger wording.
- Avoid overly abstract AI terminology.

## Localization
This modal should be written in the same localization system as the rest of the frontend. Both Chinese and English copy should be supported.

## Reuse and implementation guidance
The design should fit the existing frontend stack and visual patterns:
- Naive UI modal/dialog patterns
- existing page typography and spacing conventions
- existing i18n message structure
- existing navigation destinations such as Dashboard and Create Issue

The implementation should avoid introducing a separate onboarding subsystem if a focused modal component and lightweight persistence are sufficient.

## State and persistence expectations
Implementation details are intentionally deferred, but the design assumes:
- onboarding can be shown conditionally after login
- users can skip or complete it
- the app can remember that the modal should not auto-show repeatedly for the same user/session based on the chosen implementation approach
- there should be a way to re-open onboarding later from the product UI

## Error and edge-case expectations
- If onboarding state cannot be loaded, default behavior should not block access to the app.
- On smaller screens, the modal should remain readable and navigable.
- The final CTA destinations should always be valid routes available to authenticated users.

## Testing expectations
Implementation should be validated with frontend tests that cover:
- conditional display behavior
- step navigation
- skip/close behavior
- final CTA routing
- correct rendering of updated copy and concept hierarchy
- responsive behavior for compact layouts if already covered by the test setup

## Acceptance criteria
- The onboarding is a single three-step modal, not a full-screen tour.
- It clearly explains Codify in a way that covers welcome, concepts, and workflow.
- It presents **Codify Issue** as the workflow start.
- It does not mention GitLab Issue-triggered execution.
- It ends with two clear actions: View Dashboard and Create Issue.
- The visual and copy style fit the existing frontend.
