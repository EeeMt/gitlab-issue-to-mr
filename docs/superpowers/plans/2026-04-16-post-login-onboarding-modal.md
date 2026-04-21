# Post-login Onboarding Modal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a first-login three-step onboarding modal in the frontend that explains Codify, presents Codify Issue as the workflow start, and routes users to Dashboard or Create Issue.

**Architecture:** Add a small onboarding state helper backed by `localStorage`, render a focused modal component from `App.vue` after authenticated shell entry, and keep all copy in the existing i18n message files. Test behavior at the component and app integration levels so the onboarding can be changed without breaking login or routing flows.

**Tech Stack:** Vue 3, TypeScript, Naive UI, Vue Router, Vue I18n, Vitest, Vue Test Utils

---

## File structure

### New files
- `frontend/src/components/OnboardingModal.vue` — standalone three-step modal component with progress header, step content, navigation, skip/close handling, and final CTAs.
- `frontend/src/components/OnboardingModal.spec.ts` — unit tests for modal rendering, step navigation, emitted events, and CTA actions.
- `frontend/src/composables/useOnboarding.ts` — tiny helper for reading/writing onboarding completion state from `localStorage` safely.
- `frontend/src/composables/useOnboarding.spec.ts` — tests for persistence behavior and graceful fallback when storage access fails.
- `frontend/src/App.spec.ts` — integration tests for conditional modal display inside the authenticated app shell.

### Modified files
- `frontend/src/App.vue` — mount the onboarding helper, decide when the modal should show, handle completion/skip, and route CTA clicks.
- `frontend/src/i18n/messages/en.ts` — add English onboarding strings.
- `frontend/src/i18n/messages/zh-CN.ts` — add Chinese onboarding strings.

## Implementation notes before coding
- Keep persistence minimal: one boolean key such as `codify-onboarding-dismissed` is enough for this feature.
- Only show onboarding when all of these are true: auth initialized, authenticated, not on login/bootstrap routes, and onboarding not already dismissed.
- The modal should not own router state; it should emit semantic events (`close`, `complete`, `view-dashboard`, `create-issue`) and let `App.vue` decide navigation.
- Use existing Naive UI and app shell styles rather than inventing a new onboarding subsystem.
- All copy must describe **Codify Issue** as the start of the workflow and must not mention GitLab Issue-triggered execution.

---

### Task 1: Add onboarding persistence helper

**Files:**
- Create: `frontend/src/composables/useOnboarding.ts`
- Test: `frontend/src/composables/useOnboarding.spec.ts`

- [ ] **Step 1: Write the failing test for default state and persistence**

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  ONBOARDING_STORAGE_KEY,
  clearOnboardingDismissed,
  getOnboardingDismissed,
  setOnboardingDismissed,
} from './useOnboarding'

describe('useOnboarding', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('returns false when onboarding has not been dismissed', () => {
    expect(getOnboardingDismissed()).toBe(false)
  })

  it('persists dismissal state to localStorage', () => {
    setOnboardingDismissed(true)

    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('true')
    expect(getOnboardingDismissed()).toBe(true)
  })

  it('clears dismissal state', () => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true')

    clearOnboardingDismissed()

    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBeNull()
    expect(getOnboardingDismissed()).toBe(false)
  })

  it('fails open when storage throws', () => {
    vi.spyOn(window.localStorage, 'getItem').mockImplementation(() => {
      throw new Error('storage unavailable')
    })

    expect(getOnboardingDismissed()).toBe(false)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/composables/useOnboarding.spec.ts`
Expected: FAIL with `Failed to resolve import "./useOnboarding"` or missing export errors.

- [ ] **Step 3: Write the minimal helper implementation**

```ts
const ONBOARDING_STORAGE_KEY = 'codify-onboarding-dismissed'

function readStorage(): string | null {
  if (typeof window === 'undefined') {
    return null
  }

  try {
    return window.localStorage.getItem(ONBOARDING_STORAGE_KEY)
  } catch {
    return null
  }
}

export function getOnboardingDismissed(): boolean {
  return readStorage() === 'true'
}

export function setOnboardingDismissed(value: boolean): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.localStorage.setItem(ONBOARDING_STORAGE_KEY, value ? 'true' : 'false')
  } catch {
    // ignore storage failures so onboarding never blocks app access
  }
}

export function clearOnboardingDismissed(): void {
  if (typeof window === 'undefined') {
    return
  }

  try {
    window.localStorage.removeItem(ONBOARDING_STORAGE_KEY)
  } catch {
    // ignore storage failures so onboarding never blocks app access
  }
}

export { ONBOARDING_STORAGE_KEY }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/composables/useOnboarding.spec.ts`
Expected: PASS with 4 tests passed.

- [ ] **Step 5: Commit**

```bash
git -C /Users/AI/Projects/codify_observe add frontend/src/composables/useOnboarding.ts frontend/src/composables/useOnboarding.spec.ts
git -C /Users/AI/Projects/codify_observe commit -m "feat: add onboarding state persistence"
```

---

### Task 2: Build the onboarding modal component and localized copy

**Files:**
- Create: `frontend/src/components/OnboardingModal.vue`
- Test: `frontend/src/components/OnboardingModal.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Write the failing modal component tests**

```ts
import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import OnboardingModal from './OnboardingModal.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({
    t: (key: string) => key,
  }),
}))

vi.mock('naive-ui', () => ({
  NButton: {
    name: 'NButton',
    props: ['disabled', 'type'],
    emits: ['click'],
    setup(props: any, { slots, emit }: any) {
      return () => h('button', { disabled: props.disabled, onClick: () => emit('click') }, slots.default?.())
    },
  },
  NCard: {
    name: 'NCard',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-card' }, slots.default?.())
    },
  },
  NModal: {
    name: 'NModal',
    props: ['show'],
    setup(props: any, { slots }: any) {
      return () => props.show ? h('div', { class: 'n-modal' }, slots.default?.()) : null
    },
  },
  NProgress: {
    name: 'NProgress',
    props: ['percentage'],
    setup(props: any) {
      return () => h('div', { 'data-progress': props.percentage })
    },
  },
  NSpace: {
    name: 'NSpace',
    setup(_props: any, { slots }: any) {
      return () => h('div', { class: 'n-space' }, slots.default?.())
    },
  },
  NText: {
    name: 'NText',
    setup(_props: any, { slots }: any) {
      return () => h('span', slots.default?.())
    },
  },
}))

const mountModal = () => mount(OnboardingModal, { props: { show: true } })

describe('OnboardingModal', () => {
  it('renders the welcome step first', () => {
    const wrapper = mountModal()

    expect(wrapper.text()).toContain('onboarding.steps.welcome.title')
    expect(wrapper.text()).toContain('onboarding.actions.next')
    expect(wrapper.text()).toContain('onboarding.actions.skip')
  })

  it('moves between steps', async () => {
    const wrapper = mountModal()

    await wrapper.find('button').trigger('click')

    expect(wrapper.text()).toContain('onboarding.steps.concepts.title')
  })

  it('emits close when skip is clicked', async () => {
    const wrapper = mountModal()
    const buttons = wrapper.findAll('button')

    await buttons[0].trigger('click')

    expect(wrapper.emitted('close')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })

  it('emits view-dashboard on final primary action', async () => {
    const wrapper = mountModal()
    const next = () => wrapper.findAll('button').at(-1)!.trigger('click')

    await next()
    await next()
    await next()

    expect(wrapper.emitted('view-dashboard')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })

  it('emits create-issue on final secondary action', async () => {
    const wrapper = mountModal()
    const next = () => wrapper.findAll('button').at(-1)!.trigger('click')

    await next()
    await next()
    await wrapper.find('[data-testid="onboarding-create-issue"]').trigger('click')

    expect(wrapper.emitted('create-issue')).toHaveLength(1)
    expect(wrapper.emitted('complete')).toHaveLength(1)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/components/OnboardingModal.spec.ts`
Expected: FAIL with `Failed to resolve import "./OnboardingModal.vue"`.

- [ ] **Step 3: Add onboarding i18n copy before component implementation**

Add this block to `frontend/src/i18n/messages/en.ts` near other top-level sections:

```ts
  onboarding: {
    title: 'Welcome to Codify',
    actions: {
      skip: 'Skip introduction',
      previous: 'Previous',
      next: 'Next',
      viewDashboard: 'View Dashboard',
      createIssue: 'Create Issue'
    },
    progress: {
      welcome: '01 Welcome',
      concepts: '02 Core concepts',
      workflow: '03 Workflow'
    },
    steps: {
      welcome: {
        title: 'Welcome to Codify',
        subtitle: 'Start from a Codify Issue and move work toward executable tasks, code changes, and Merge Requests.',
        points: {
          issues: 'Use Issues to organize development goals',
          tasks: 'Use Tasks to track execution and outcomes',
          results: 'Turn results into branches and Merge Requests'
        },
        diagram: {
          issue: 'Codify Issue',
          task: 'Task',
          worker: 'AI Worker',
          result: 'Branch / Merge Request'
        }
      },
      concepts: {
        title: 'Get familiar with the core objects',
        summary: 'Issue defines the goal, Task drives execution, Worker performs the work, and MR carries the result.',
        cards: {
          issue: {
            title: 'Issue',
            body: 'Codify\'s internal requirement object and the starting point of the workflow.'
          },
          task: {
            title: 'Task',
            body: 'An execution unit created around an Issue, carrying prompt, status, and result.'
          },
          worker: {
            title: 'Worker',
            body: 'The isolated execution unit that handles code generation and workflow steps.'
          },
          mr: {
            title: 'Merge Request',
            body: 'The review surface for generated code output and follow-up collaboration.'
          }
        }
      },
      workflow: {
        title: 'How work moves to code changes',
        ending: 'You now have the core model. Start by checking the system overview or creating a new Issue.',
        items: {
          issue: {
            title: 'Create Issue',
            body: 'Create a Codify Issue with background, objective, and expected result.'
          },
          task: {
            title: 'Generate Task',
            body: 'Create a Task from that Issue and fill in the execution prompt and parameters.'
          },
          schedule: {
            title: 'Enter scheduling',
            body: 'Scheduler arranges execution by queue and priority.'
          },
          execute: {
            title: 'Execute generation',
            body: 'Worker runs in an isolated environment, generates code, commits a branch, and records progress.'
          },
          result: {
            title: 'Produce result',
            body: 'The system creates a Merge Request for review and follow-up collaboration.'
          }
        }
      }
    }
  },
```

Add the corresponding localized block to `frontend/src/i18n/messages/zh-CN.ts`:

```ts
  onboarding: {
    title: '欢迎使用 Codify',
    actions: {
      skip: '跳过介绍',
      previous: '上一步',
      next: '下一步',
      viewDashboard: '查看 Dashboard',
      createIssue: '创建需求'
    },
    progress: {
      welcome: '01 简介',
      concepts: '02 核心概念',
      workflow: '03 工作流程'
    },
    steps: {
      welcome: {
        title: '欢迎使用 Codify',
        subtitle: '从 Codify Issue 出发，将需求逐步推进为可执行任务、代码变更和 Merge Request。',
        points: {
          issues: '用 Issue 组织需求和改动目标',
          tasks: '用 Task 跟踪执行状态与结果',
          results: '将产出沉淀为分支与 Merge Request'
        },
        diagram: {
          issue: 'Codify Issue',
          task: 'Task',
          worker: 'AI Worker',
          result: '分支 / Merge Request'
        }
      },
      concepts: {
        title: '先认识系统里的几个核心对象',
        summary: 'Issue 定义目标，Task 推动执行，Worker 完成处理，MR 承载结果。',
        cards: {
          issue: {
            title: 'Issue',
            body: 'Codify 内部的需求对象，是整个工作流的起点。'
          },
          task: {
            title: 'Task',
            body: '围绕某个 Issue 发起的一次执行任务，负责承载提示词、状态和结果。'
          },
          worker: {
            title: 'Worker',
            body: '实际执行任务的工作单元，会在隔离环境中处理代码生成与提交流程。'
          },
          mr: {
            title: 'Merge Request',
            body: '任务产出的代码审阅入口，用来查看变更、继续协作和完成合并。'
          }
        }
      },
      workflow: {
        title: '系统如何把一个需求推进到代码变更',
        ending: '现在你已经了解了系统的核心概念和基本流程。你可以先查看全局运行情况，或者直接创建一个新的 Issue。',
        items: {
          issue: {
            title: '创建 Issue',
            body: '在 Codify 中创建一个 Issue，明确需求背景、目标和预期结果。'
          },
          task: {
            title: '生成 Task',
            body: '基于该 Issue 创建执行任务，填写提示词和执行参数。'
          },
          schedule: {
            title: '进入调度',
            body: 'Scheduler 根据队列和优先级安排执行。'
          },
          execute: {
            title: '执行生成',
            body: 'Worker 在隔离环境中生成代码、提交分支并记录过程。'
          },
          result: {
            title: '产出结果',
            body: '系统生成 Merge Request，用于查看变更、继续协作和完成合并。'
          }
        }
      }
    }
  },
```

- [ ] **Step 4: Implement the modal component**

Create `frontend/src/components/OnboardingModal.vue` with this structure:

```vue
<template>
  <n-modal :show="show" :mask-closable="false" preset="card" class="onboarding-modal" @close="handleDismiss">
    <n-card :bordered="false" class="onboarding-modal__card">
      <div class="onboarding-modal__header">
        <div>
          <div class="onboarding-modal__eyebrow">{{ t('onboarding.title') }}</div>
          <h2 class="onboarding-modal__title">{{ stepTitle }}</h2>
        </div>
        <n-button quaternary circle data-testid="onboarding-close" @click="handleDismiss">
          <template #icon>
            <n-icon :component="CloseOutline" />
          </template>
        </n-button>
      </div>

      <div class="onboarding-modal__progress">
        <div class="onboarding-modal__progress-labels">
          <span>{{ t('onboarding.progress.welcome') }}</span>
          <span>{{ t('onboarding.progress.concepts') }}</span>
          <span>{{ t('onboarding.progress.workflow') }}</span>
        </div>
        <n-progress type="line" :show-indicator="false" :percentage="progressPercentage" />
      </div>

      <section v-if="step === 0" class="onboarding-modal__body onboarding-modal__body--hero">
        <div class="onboarding-diagram onboarding-diagram--hero">
          <div class="onboarding-diagram__node">{{ t('onboarding.steps.welcome.diagram.issue') }}</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">{{ t('onboarding.steps.welcome.diagram.task') }}</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">{{ t('onboarding.steps.welcome.diagram.worker') }}</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">{{ t('onboarding.steps.welcome.diagram.result') }}</div>
        </div>
        <div class="onboarding-copy">
          <p class="onboarding-copy__subtitle">{{ t('onboarding.steps.welcome.subtitle') }}</p>
          <ul class="onboarding-copy__points">
            <li>{{ t('onboarding.steps.welcome.points.issues') }}</li>
            <li>{{ t('onboarding.steps.welcome.points.tasks') }}</li>
            <li>{{ t('onboarding.steps.welcome.points.results') }}</li>
          </ul>
        </div>
      </section>

      <section v-else-if="step === 1" class="onboarding-modal__body">
        <div class="onboarding-diagram onboarding-diagram--concepts">
          <div class="onboarding-diagram__node">Issue</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">Task</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">Worker</div>
          <div class="onboarding-diagram__arrow">→</div>
          <div class="onboarding-diagram__node">MR</div>
        </div>
        <div class="onboarding-grid">
          <article v-for="card in conceptCards" :key="card.title" class="onboarding-grid__card">
            <h3>{{ card.title }}</h3>
            <p>{{ card.body }}</p>
          </article>
        </div>
        <p class="onboarding-copy__summary">{{ t('onboarding.steps.concepts.summary') }}</p>
      </section>

      <section v-else class="onboarding-modal__body">
        <div class="onboarding-timeline">
          <article v-for="item in workflowItems" :key="item.title" class="onboarding-timeline__item">
            <div class="onboarding-timeline__marker" />
            <div>
              <h3>{{ item.title }}</h3>
              <p>{{ item.body }}</p>
            </div>
          </article>
        </div>
        <p class="onboarding-copy__summary">{{ t('onboarding.steps.workflow.ending') }}</p>
      </section>

      <div class="onboarding-modal__footer">
        <n-button quaternary data-testid="onboarding-skip" @click="handleDismiss">
          {{ t('onboarding.actions.skip') }}
        </n-button>

        <div class="onboarding-modal__footer-actions">
          <n-button v-if="step > 0" @click="step -= 1">
            {{ t('onboarding.actions.previous') }}
          </n-button>
          <n-button v-if="step < LAST_STEP" type="primary" data-testid="onboarding-next" @click="step += 1">
            {{ t('onboarding.actions.next') }}
          </n-button>
          <template v-else>
            <n-button data-testid="onboarding-create-issue" @click="handleCreateIssue">
              {{ t('onboarding.actions.createIssue') }}
            </n-button>
            <n-button type="primary" data-testid="onboarding-view-dashboard" @click="handleViewDashboard">
              {{ t('onboarding.actions.viewDashboard') }}
            </n-button>
          </template>
        </div>
      </div>
    </n-card>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NCard, NIcon, NModal, NProgress } from 'naive-ui'
import { CloseOutline } from '@vicons/ionicons5'

const props = defineProps<{ show: boolean }>()
const emit = defineEmits<{
  close: []
  complete: []
  'view-dashboard': []
  'create-issue': []
}>()

const { t } = useI18n()
const LAST_STEP = 2
const step = ref(0)

const stepTitle = computed(() => {
  if (step.value === 0) return t('onboarding.steps.welcome.title')
  if (step.value === 1) return t('onboarding.steps.concepts.title')
  return t('onboarding.steps.workflow.title')
})

const progressPercentage = computed(() => ((step.value + 1) / (LAST_STEP + 1)) * 100)

const conceptCards = computed(() => [
  { title: t('onboarding.steps.concepts.cards.issue.title'), body: t('onboarding.steps.concepts.cards.issue.body') },
  { title: t('onboarding.steps.concepts.cards.task.title'), body: t('onboarding.steps.concepts.cards.task.body') },
  { title: t('onboarding.steps.concepts.cards.worker.title'), body: t('onboarding.steps.concepts.cards.worker.body') },
  { title: t('onboarding.steps.concepts.cards.mr.title'), body: t('onboarding.steps.concepts.cards.mr.body') },
])

const workflowItems = computed(() => [
  { title: t('onboarding.steps.workflow.items.issue.title'), body: t('onboarding.steps.workflow.items.issue.body') },
  { title: t('onboarding.steps.workflow.items.task.title'), body: t('onboarding.steps.workflow.items.task.body') },
  { title: t('onboarding.steps.workflow.items.schedule.title'), body: t('onboarding.steps.workflow.items.schedule.body') },
  { title: t('onboarding.steps.workflow.items.execute.title'), body: t('onboarding.steps.workflow.items.execute.body') },
  { title: t('onboarding.steps.workflow.items.result.title'), body: t('onboarding.steps.workflow.items.result.body') },
])

function finish() {
  emit('complete')
  emit('close')
}

function handleDismiss() {
  finish()
}

function handleViewDashboard() {
  emit('complete')
  emit('view-dashboard')
  emit('close')
}

function handleCreateIssue() {
  emit('complete')
  emit('create-issue')
  emit('close')
}
</script>
```

Add scoped styles in the same file for:
- desktop two-column step 1 layout
- 2x2 concept card grid
- vertical mobile stacking under `@media (max-width: 768px)`
- large modal width near `min(960px, calc(100vw - 32px))`
- lightweight gradient/card styling matching current app shell

- [ ] **Step 5: Run modal tests to verify they pass**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/components/OnboardingModal.spec.ts`
Expected: PASS with 5 tests passed.

- [ ] **Step 6: Commit**

```bash
git -C /Users/AI/Projects/codify_observe add frontend/src/components/OnboardingModal.vue frontend/src/components/OnboardingModal.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git -C /Users/AI/Projects/codify_observe commit -m "feat: add localized onboarding modal"
```

---

### Task 3: Integrate onboarding into App.vue

**Files:**
- Modify: `frontend/src/App.vue`
- Test: `frontend/src/App.spec.ts`
- Reuse: `frontend/src/composables/useOnboarding.ts`
- Reuse: `frontend/src/components/OnboardingModal.vue`

- [ ] **Step 1: Write the failing app integration tests**

Create `frontend/src/App.spec.ts`:

```ts
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { mount, flushPromises } from '@vue/test-utils'
import { defineComponent, h, nextTick, reactive } from 'vue'

const mockPush = vi.fn()
const mockInitializeAuth = vi.fn()
const mockGetOnboardingDismissed = vi.fn()
const mockSetOnboardingDismissed = vi.fn()
const authState = reactive({
  initialized: true,
  authenticated: true,
  oidcEnabled: true,
  user: { username: 'demo', display_name: 'Demo User', avatar_url: null, platform_role: 'platform_admin' },
})

vi.mock('./auth', () => ({
  authState,
  canAccessSharedPage: () => true,
  initializeAuth: mockInitializeAuth,
  isAdmin: { value: true },
  logoutAndClearAuth: vi.fn(),
}))

vi.mock('./composables/useOnboarding', () => ({
  getOnboardingDismissed: mockGetOnboardingDismissed,
  setOnboardingDismissed: mockSetOnboardingDismissed,
}))

vi.mock('./components/OnboardingModal.vue', () => ({
  default: defineComponent({
    emits: ['close', 'complete', 'view-dashboard', 'create-issue'],
    setup(_props, { emit }) {
      return () => h('div', { 'data-testid': 'onboarding-modal' }, [
        h('button', { onClick: () => { emit('complete'); emit('close') } }, 'dismiss'),
        h('button', { 'data-testid': 'go-dashboard', onClick: () => { emit('complete'); emit('view-dashboard'); emit('close') } }, 'dashboard'),
        h('button', { 'data-testid': 'go-create-issue', onClick: () => { emit('complete'); emit('create-issue'); emit('close') } }, 'issue'),
      ])
    },
  }),
}))

vi.mock('vue-router', () => ({
  useRouter: () => ({ push: mockPush }),
  useRoute: () => ({ name: 'Dashboard' }),
  RouterView: defineComponent({ name: 'RouterView', setup: () => () => h('div', 'view') }),
}))

vi.mock('./components/LanguageToggle.vue', () => ({ default: defineComponent({ setup: () => () => h('div') }) }))
vi.mock('./composables/useBreakpoints', () => ({ useBreakpoints: () => ({ isMobile: { value: false } }) }))
vi.mock('./i18n', () => ({ naiveUiLocale: { value: {} }, naiveUiDateLocale: { value: {} } }))
vi.mock('vue-i18n', () => ({ useI18n: () => ({ t: (key: string) => key }) }))
vi.mock('naive-ui', () => ({
  NAvatar: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NButton: defineComponent({ emits: ['click'], setup: (_p, { slots, emit }) => () => h('button', { onClick: () => emit('click') }, slots.default?.()) }),
  NConfigProvider: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NDialogProvider: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NDrawer: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NDrawerContent: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NIcon: defineComponent({ setup: () => () => h('i') }),
  NLayout: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NLayoutSider: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NMenu: defineComponent({ setup: () => () => h('div') }),
  NMessageProvider: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NSpin: defineComponent({ setup: (_p, { slots }) => () => h('div', slots.default?.()) }),
  NText: defineComponent({ setup: (_p, { slots }) => () => h('span', slots.default?.()) }),
}))

import App from './App.vue'

const mountApp = () => mount(App, { global: { stubs: { 'router-view': true } } })

describe('App onboarding', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockInitializeAuth.mockResolvedValue(undefined)
    mockGetOnboardingDismissed.mockReturnValue(false)
    authState.initialized = true
    authState.authenticated = true
  })

  it('shows onboarding for authenticated users when not dismissed', () => {
    const wrapper = mountApp()
    expect(wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(true)
  })

  it('does not show onboarding when already dismissed', () => {
    mockGetOnboardingDismissed.mockReturnValue(true)
    const wrapper = mountApp()
    expect(wrapper.find('[data-testid="onboarding-modal"]').exists()).toBe(false)
  })

  it('persists dismissal when onboarding closes', async () => {
    const wrapper = mountApp()
    await wrapper.find('button').trigger('click')
    expect(mockSetOnboardingDismissed).toHaveBeenCalledWith(true)
  })

  it('routes to dashboard from final CTA', async () => {
    const wrapper = mountApp()
    await wrapper.find('[data-testid="go-dashboard"]').trigger('click')
    expect(mockPush).toHaveBeenCalledWith({ name: 'Dashboard' })
  })

  it('routes to create issue from final CTA', async () => {
    const wrapper = mountApp()
    await wrapper.find('[data-testid="go-create-issue"]').trigger('click')
    expect(mockPush).toHaveBeenCalledWith({ name: 'CreateIssue' })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/App.spec.ts`
Expected: FAIL because `OnboardingModal` is not rendered by `App.vue` yet.

- [ ] **Step 3: Integrate onboarding state and handlers into `App.vue`**

Update the script section in `frontend/src/App.vue` with these additions:

```ts
import { computed, h, onMounted, ref, watch } from 'vue'
import OnboardingModal from './components/OnboardingModal.vue'
import { getOnboardingDismissed, setOnboardingDismissed } from './composables/useOnboarding'
```

Add state near the existing refs:

```ts
const showOnboarding = ref(false)
```

Add the computed guard after `showShell`:

```ts
const canShowOnboarding = computed(
  () => authState.initialized && authState.authenticated && showShell.value
)
```

Add handlers below `handleLogout`:

```ts
function dismissOnboarding() {
  setOnboardingDismissed(true)
  showOnboarding.value = false
}

function handleOnboardingViewDashboard() {
  dismissOnboarding()
  router.push({ name: 'Dashboard' })
}

function handleOnboardingCreateIssue() {
  dismissOnboarding()
  router.push({ name: 'CreateIssue' })
}
```

Add the watcher before `onMounted`:

```ts
watch(
  canShowOnboarding,
  (value) => {
    if (!value) {
      showOnboarding.value = false
      return
    }

    showOnboarding.value = !getOnboardingDismissed()
  },
  { immediate: true }
)
```

Then render the modal inside the authenticated shell layout, after the content area so it overlays the shell:

```vue
<OnboardingModal
  :show="showOnboarding"
  @close="dismissOnboarding"
  @complete="dismissOnboarding"
  @view-dashboard="handleOnboardingViewDashboard"
  @create-issue="handleOnboardingCreateIssue"
/>
```

Use this exact event wiring instead if duplicate persistence calls appear during testing:

```vue
<OnboardingModal
  :show="showOnboarding"
  @close="showOnboarding = false"
  @complete="dismissOnboarding"
  @view-dashboard="handleOnboardingViewDashboard"
  @create-issue="handleOnboardingCreateIssue"
/>
```

Choose the second version if the first causes multiple `setOnboardingDismissed(true)` calls in a single interaction.

- [ ] **Step 4: Run app integration tests to verify they pass**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/App.spec.ts`
Expected: PASS with 5 tests passed.

- [ ] **Step 5: Commit**

```bash
git -C /Users/AI/Projects/codify_observe add frontend/src/App.vue frontend/src/App.spec.ts
git -C /Users/AI/Projects/codify_observe commit -m "feat: show onboarding modal after login"
```

---

### Task 4: Verify the full onboarding slice

**Files:**
- Verify: `frontend/src/composables/useOnboarding.spec.ts`
- Verify: `frontend/src/components/OnboardingModal.spec.ts`
- Verify: `frontend/src/App.spec.ts`

- [ ] **Step 1: Run the targeted onboarding test set**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/composables/useOnboarding.spec.ts src/components/OnboardingModal.spec.ts src/App.spec.ts`
Expected: PASS with all onboarding-focused tests green.

- [ ] **Step 2: Run the existing related view tests to catch routing or shell regressions**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run src/views/Login.spec.ts src/views/CreateIssue.spec.ts`
Expected: PASS with no regression in login or issue creation flow.

- [ ] **Step 3: Run the frontend test suite if the targeted tests pass cleanly**

Run: `cd /Users/AI/Projects/codify_observe/frontend && npx vitest run`
Expected: PASS, or failures limited to unrelated pre-existing tests that are documented before merge.

- [ ] **Step 4: Commit verification-only follow-ups if needed**

```bash
git -C /Users/AI/Projects/codify_observe status --short
```

Expected: no unexpected file changes. If code changed while fixing tests, create a new commit describing the fix, for example:

```bash
git -C /Users/AI/Projects/codify_observe add frontend/src/App.vue frontend/src/components/OnboardingModal.vue frontend/src/components/OnboardingModal.spec.ts frontend/src/composables/useOnboarding.spec.ts
git -C /Users/AI/Projects/codify_observe commit -m "test: cover onboarding modal flow"
```

---

## Self-review

### Spec coverage
- Single three-step modal: covered by Task 2 component structure and tests.
- Welcome, concepts, workflow content: covered by Task 2 i18n additions and modal body implementation.
- Codify Issue as workflow start: explicitly encoded in the copy added in Task 2.
- No GitLab Issue-trigger wording: enforced by the i18n copy content in Task 2.
- Conditional display after login: covered by Task 3 app integration and tests.
- Final CTA routing to Dashboard and Create Issue: covered by Task 3 handlers and tests.
- Responsive stacking and lightweight visual fit: covered by Task 2 style requirements.
- Persistence / no repeated interruption intent: covered by Task 1 helper plus Task 3 integration.

### Placeholder scan
- No TODO/TBD markers remain.
- Every code-writing step includes concrete code blocks.
- Every verification step has an exact command and expected result.

### Type consistency
- Storage API names are consistent: `getOnboardingDismissed`, `setOnboardingDismissed`, `clearOnboardingDismissed`.
- Modal events are consistent: `close`, `complete`, `view-dashboard`, `create-issue`.
- Final route names are consistent with the router: `Dashboard`, `CreateIssue`.

