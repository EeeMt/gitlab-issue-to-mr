# Config Modal Unification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Unify Config page add/edit flows so AI providers, prompt templates, and Mattermost notification profiles all use modal-based editors on desktop and mobile.

**Architecture:** Keep each panel's existing local form state, validation, and API calls, but replace inconsistent edit surfaces with `n-modal`-based editors. AI Providers switch from drawer to modal, Prompt Templates move from inline editor to modal, and Mattermost notification profiles stay modal but get aligned close/reset behavior and tests.

**Tech Stack:** Vue 3, Naive UI (`n-modal`, `n-form`, `n-data-table`), Vitest, vue-test-utils, TypeScript

---

## File Map

- `frontend/src/components/config/AIProvidersPanel.vue`
  - Replace the drawer editor with a modal editor while preserving current create/edit/save/delete/set-default behavior.
- `frontend/src/components/config/AIProvidersPanel.spec.ts`
  - New focused unit test file for AI provider modal create/edit/save-close flows.
- `frontend/src/views/config/PromptTemplatesPanel.vue`
  - Remove inline editor block and move prompt template editing into a modal while keeping the existing `VariableEditor` and variable-tip validation.
- `frontend/src/views/config/PromptTemplatesPanel.spec.ts`
  - Update assertions and stubs from inline editor behavior to modal behavior.
- `frontend/src/components/config/MattermostNotificationsPanel.vue`
  - Keep modal editing, but introduce explicit close/reset helper(s) so cancel/X/save all leave the modal in a clean state.
- `frontend/src/components/config/MattermostNotificationsPanel.spec.ts`
  - New focused unit test file for notification profile modal open/edit/close/reset behavior.
- `frontend/src/views/Config.spec.ts`
  - Only adjust if panel import/stub behavior changes or new panel tests reveal a parent-level expectation that no longer matches reality.

---

### Task 1: AI Providers — convert drawer editing to modal and add focused tests

**Files:**
- Modify: `frontend/src/components/config/AIProvidersPanel.vue`
- Create: `frontend/src/components/config/AIProvidersPanel.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/config/AIProvidersPanel.spec.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import AIProvidersPanel from './AIProvidersPanel.vue'

const mockApi = {
  getProviders: vi.fn(),
  createProvider: vi.fn(),
  updateProvider: vi.fn(),
  deleteProvider: vi.fn(),
  setDefaultProvider: vi.fn()
}

vi.mock('../../api', () => ({
  getProviders: (...args: any[]) => mockApi.getProviders(...args),
  createProvider: (...args: any[]) => mockApi.createProvider(...args),
  updateProvider: (...args: any[]) => mockApi.updateProvider(...args),
  deleteProvider: (...args: any[]) => mockApi.deleteProvider(...args),
  setDefaultProvider: (...args: any[]) => mockApi.setDefaultProvider(...args)
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

vi.mock('naive-ui', () => ({
  NCard: { setup: (_p: any, { slots }: any) => () => h('div', { class: 'n-card' }, [slots.header?.(), slots['header-extra']?.(), slots.default?.()]) },
  NDataTable: { props: ['data'], setup: (props: any) => () => h('div', { class: 'n-data-table' }, props.data?.map((row: any) => h('div', { key: row.id, class: 'provider-row' }, row.name))) },
  NModal: { props: ['show'], emits: ['update:show'], setup: (props: any, { slots }: any) => () => props.show ? h('div', { class: 'n-modal', 'data-testid': 'ai-provider-modal' }, [slots.default?.(), slots.footer?.()]) : null },
  NForm: { setup: (_p: any, { slots }: any) => () => h('form', { class: 'n-form' }, slots.default?.()) },
  NFormItem: { setup: (_p: any, { slots }: any) => () => h('div', { class: 'n-form-item' }, [slots.default?.(), slots.feedback?.()]) },
  NInput: { props: ['value'], emits: ['update:value'], setup: (props: any, { emit, attrs }: any) => () => h('input', { ...attrs, value: props.value, onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value) }) },
  NInputNumber: { props: ['value'], emits: ['update:value'], setup: (props: any, { emit }: any) => () => h('input', { type: 'number', value: props.value, onInput: (e: Event) => emit('update:value', Number((e.target as HTMLInputElement).value)) }) },
  NButton: { emits: ['click'], setup: (_p: any, { slots, emit, attrs }: any) => () => h('button', { ...attrs, onClick: () => emit('click') }, slots.default?.()) },
  NPopconfirm: { setup: (_p: any, { slots }: any) => () => h('div', { class: 'n-popconfirm' }, [slots.trigger?.(), slots.default?.()]) },
  NSpace: { setup: (_p: any, { slots }: any) => () => h('div', { class: 'n-space' }, slots.default?.()) },
  NTag: { setup: (_p: any, { slots }: any) => () => h('span', { class: 'n-tag' }, slots.default?.()) },
  useMessage: () => ({ success: vi.fn(), error: vi.fn() })
}))

describe('AIProvidersPanel', () => {
  const providers = [
    { id: 1, name: 'default', base_url: 'https://api.example.com', model: 'claude', max_turns: 20, api_key_configured: true, system_prompt: 'hi', is_default: true }
  ]

  beforeEach(() => {
    vi.clearAllMocks()
    mockApi.getProviders.mockResolvedValue(providers)
    mockApi.createProvider.mockResolvedValue(providers[0])
    mockApi.updateProvider.mockResolvedValue(providers[0])
  })

  it('opens create modal with empty form state', async () => {
    const wrapper = mount(AIProvidersPanel, { props: { isMobile: false } })
    await vi.waitFor(() => expect(mockApi.getProviders).toHaveBeenCalled())

    wrapper.vm.openCreate()

    expect(wrapper.vm.modalVisible).toBe(true)
    expect(wrapper.vm.editingProvider).toBeNull()
    expect(wrapper.find('[data-testid="ai-provider-modal"]').exists()).toBe(true)
  })

  it('opens edit modal with provider values', async () => {
    const wrapper = mount(AIProvidersPanel, { props: { isMobile: false } })
    await vi.waitFor(() => expect(mockApi.getProviders).toHaveBeenCalled())

    wrapper.vm.openEdit(providers[0])

    expect(wrapper.vm.modalVisible).toBe(true)
    expect(wrapper.vm.formValue.name).toBe('default')
    expect(wrapper.vm.formValue.base_url).toBe('https://api.example.com')
  })

  it('closes modal after successful save', async () => {
    const wrapper = mount(AIProvidersPanel, { props: { isMobile: false } })
    await vi.waitFor(() => expect(mockApi.getProviders).toHaveBeenCalled())

    wrapper.vm.formRef = { validate: vi.fn().mockResolvedValue(undefined) }
    wrapper.vm.openCreate()
    wrapper.vm.formValue.name = 'new-provider'
    wrapper.vm.formValue.base_url = 'https://api.example.com'
    wrapper.vm.formValue.model = 'claude'
    wrapper.vm.formValue.max_turns = 20

    await wrapper.vm.handleSave()

    expect(mockApi.createProvider).toHaveBeenCalled()
    expect(wrapper.vm.modalVisible).toBe(false)
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/config/AIProvidersPanel.spec.ts`

Expected: FAIL because `AIProvidersPanel.vue` still uses `drawerVisible`, `NDrawer`, and exposes no `modalVisible` state.

- [ ] **Step 3: Write the minimal implementation**

In `frontend/src/components/config/AIProvidersPanel.vue`, replace the drawer imports and markup with modal equivalents:

```ts
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSpace,
  NTag,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules
} from 'naive-ui'

const modalVisible = ref(false)

function closeModal() {
  modalVisible.value = false
  if (!editingProvider.value) {
    resetForm()
  }
}

function openCreate() {
  editingProvider.value = null
  resetForm()
  modalVisible.value = true
}

function openEdit(provider: AIProvider) {
  editingProvider.value = provider
  formValue.value = {
    name: provider.name,
    base_url: provider.base_url,
    model: provider.model,
    max_turns: provider.max_turns,
    api_key: '',
    system_prompt: provider.system_prompt || ''
  }
  modalVisible.value = true
}
```

Replace the template block:

```vue
<n-modal
  v-model:show="modalVisible"
  preset="card"
  :title="editingProvider ? t('config.providers.edit') : t('config.providers.create')"
  :style="{ width: isMobile ? '96vw' : '560px' }"
>
  <n-form
    ref="formRef"
    :model="formValue"
    :rules="rules"
    label-placement="top"
    class="config-section-form"
  >
    <!-- keep existing form items unchanged -->
  </n-form>

  <template #footer>
    <n-space justify="end">
      <n-button @click="closeModal">{{ t('common.cancel') }}</n-button>
      <n-button type="primary" :loading="saving" @click="handleSave">
        {{ t('common.save') }}
      </n-button>
    </n-space>
  </template>
</n-modal>
```

And update the save success path:

```ts
    modalVisible.value = false
    await fetchProviders()
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/config/AIProvidersPanel.spec.ts`

Expected: PASS with 3 passing tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config/AIProvidersPanel.vue frontend/src/components/config/AIProvidersPanel.spec.ts
git commit -m "feat: use modal editor for AI providers"
```

---

### Task 2: Prompt Templates — replace inline editor with modal and update tests

**Files:**
- Modify: `frontend/src/views/config/PromptTemplatesPanel.vue`
- Modify: `frontend/src/views/config/PromptTemplatesPanel.spec.ts`

- [ ] **Step 1: Update tests to describe modal behavior first**

In `frontend/src/views/config/PromptTemplatesPanel.spec.ts`, update the mocked Naive UI exports to include `NModal`:

```ts
  NModal: {
    name: 'NModal',
    props: ['show', 'preset', 'title', 'style'],
    emits: ['update:show'],
    setup(props: any, { slots }: any) {
      return () => props.show
        ? h('div', { class: 'n-modal', 'data-testid': 'prompt-template-modal' }, [
            slots.default?.(),
            slots.footer?.()
          ])
        : null
    }
  },
```

Then update the assertions:

```ts
it('should reset form and open modal', async () => {
  const wrapper = mountComponent()
  await vi.waitFor(() => {})

  wrapper.vm.handleCreatePromptTemplate()

  expect(wrapper.vm.promptTemplateEditingId).toBeNull()
  expect(wrapper.vm.promptTemplateModalVisible).toBe(true)
  expect(wrapper.find('[data-testid="prompt-template-modal"]').exists()).toBe(true)
})

it('should populate form with template data and open modal', async () => {
  const wrapper = mountComponent()
  await vi.waitFor(() => {})

  wrapper.vm.handleEditPromptTemplate(mockTemplates[0])

  expect(wrapper.vm.promptTemplateEditingId).toBe(1)
  expect(wrapper.vm.promptTemplateModalVisible).toBe(true)
})

it('should close modal and reset form state', async () => {
  const wrapper = mountComponent()
  await vi.waitFor(() => {})

  wrapper.vm.handleCreatePromptTemplate()
  wrapper.vm.promptTemplateForm.name = 'Draft'
  wrapper.vm.handleCancelPromptTemplateEditing()

  expect(wrapper.vm.promptTemplateModalVisible).toBe(false)
  expect(wrapper.vm.promptTemplateForm.name).toBe('')
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/views/config/PromptTemplatesPanel.spec.ts`

Expected: FAIL because `PromptTemplatesPanel.vue` still exposes `promptTemplateEditorVisible` and renders the inline editor instead of a modal.

- [ ] **Step 3: Move the editor into a modal**

In `frontend/src/views/config/PromptTemplatesPanel.vue`, replace inline-editor state and markup:

```ts
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NModal,
  NPopconfirm,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  type DataTableColumns,
  type FormInst
} from 'naive-ui'

const promptTemplateModalVisible = ref(false)

function handleCreatePromptTemplate() {
  resetPromptTemplateForm()
  promptTemplateModalVisible.value = true
}

function handleEditPromptTemplate(template: PromptTemplate) {
  promptTemplateEditingId.value = template.id
  promptTemplateForm.name = template.name
  promptTemplateForm.content = template.content
  promptTemplateForm.variable_tips = template.variable_tips ? { ...template.variable_tips } : {}
  promptTemplateForm.is_active = template.is_active
  promptTemplateModalVisible.value = true
}

function handleCancelPromptTemplateEditing() {
  promptTemplateModalVisible.value = false
  resetPromptTemplateForm()
}
```

Replace the inline editor block with:

```vue
<n-modal
  v-model:show="promptTemplateModalVisible"
  preset="card"
  :title="promptTemplateEditingId ? t('config.editPromptTemplate') : t('config.createPromptTemplate')"
  :style="{ width: isMobile ? '96vw' : '860px' }"
>
  <n-form ref="promptTemplateFormRef" :model="promptTemplateForm" label-placement="top" class="config-section-form">
    <div class="config-form__section">
      <div class="config-form__section-title">{{ t('config.promptTemplateEditorSection') }}</div>
      <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
        <n-gi>
          <n-form-item :label="t('config.promptTemplateName')" path="name" required>
            <n-input
              v-model:value="promptTemplateForm.name"
              class="config-form__input"
              data-testid="prompt-template-name-input"
              :placeholder="t('config.promptTemplateNamePlaceholder')"
            />
            <template #feedback>
              {{ t('config.promptTemplateNameHint') }}
            </template>
          </n-form-item>
        </n-gi>
        <n-gi>
          <n-form-item :label="t('config.promptTemplateActive')" path="is_active">
            <n-switch
              v-model:value="promptTemplateForm.is_active"
              data-testid="prompt-template-active-switch"
            />
            <template #feedback>
              {{ t('config.promptTemplateActiveHint') }}
            </template>
          </n-form-item>
        </n-gi>
        <n-gi :span="isMobile ? 1 : 2">
          <n-form-item :label="t('config.promptTemplateContent')" path="content" required>
            <VariableEditor
              data-testid="prompt-template-content-editor"
              v-model="promptTemplateForm.content"
              :variable-tips="promptTemplateForm.variable_tips"
              editable
              @update:variable-tips="handlePromptTemplateVariableTipsUpdate"
            />
            <template #feedback>
              {{ t('config.promptTemplateContentHint') }}
            </template>
          </n-form-item>
        </n-gi>
      </n-grid>
    </div>
  </n-form>

  <template #footer>
    <n-space justify="end">
      <n-button data-testid="prompt-template-cancel-button" @click="handleCancelPromptTemplateEditing">
        {{ t('common.cancel') }}
      </n-button>
      <n-button type="primary" data-testid="prompt-template-save-button" @click="handleSavePromptTemplate">
        {{ t('common.save') }}
      </n-button>
    </n-space>
  </template>
</n-modal>
```

Keep the existing variable-tip validation and save logic, but rely on `handleCancelPromptTemplateEditing()` to close/reset after successful save.

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/views/config/PromptTemplatesPanel.spec.ts`

Expected: PASS with updated modal-based assertions.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/views/config/PromptTemplatesPanel.vue frontend/src/views/config/PromptTemplatesPanel.spec.ts
git commit -m "feat: move prompt template editor into modal"
```

---

### Task 3: Mattermost notification profiles — align modal close/reset behavior and add focused tests

**Files:**
- Modify: `frontend/src/components/config/MattermostNotificationsPanel.vue`
- Create: `frontend/src/components/config/MattermostNotificationsPanel.spec.ts`

- [ ] **Step 1: Write the failing tests**

Create `frontend/src/components/config/MattermostNotificationsPanel.spec.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { h } from 'vue'
import MattermostNotificationsPanel from './MattermostNotificationsPanel.vue'

const mockApi = {
  getMattermostNotificationConfig: vi.fn(),
  createMattermostNotificationProfile: vi.fn(),
  updateMattermostNotificationProfile: vi.fn(),
  deleteMattermostNotificationProfile: vi.fn(),
  updateMattermostIntegration: vi.fn(),
  testMattermostIntegration: vi.fn()
}

vi.mock('../../api', () => ({
  getMattermostNotificationConfig: (...args: any[]) => mockApi.getMattermostNotificationConfig(...args),
  createMattermostNotificationProfile: (...args: any[]) => mockApi.createMattermostNotificationProfile(...args),
  updateMattermostNotificationProfile: (...args: any[]) => mockApi.updateMattermostNotificationProfile(...args),
  deleteMattermostNotificationProfile: (...args: any[]) => mockApi.deleteMattermostNotificationProfile(...args),
  updateMattermostIntegration: (...args: any[]) => mockApi.updateMattermostIntegration(...args),
  testMattermostIntegration: (...args: any[]) => mockApi.testMattermostIntegration(...args)
}))

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

vi.mock('naive-ui', () => ({
  NSpin: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NCard: { setup: (_p: any, { slots }: any) => () => h('div', { class: 'n-card' }, [slots.header?.(), slots.default?.()]) },
  NModal: { props: ['show'], emits: ['update:show'], setup: (props: any, { slots }: any) => () => props.show ? h('div', { class: 'n-modal', 'data-testid': 'notification-profile-modal' }, [slots.default?.(), slots.footer?.()]) : null },
  NForm: { setup: (_p: any, { slots }: any) => () => h('form', slots.default?.()) },
  NFormItem: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NGrid: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NGi: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NInput: { props: ['value'], emits: ['update:value'], setup: (props: any, { emit }: any) => () => h('input', { value: props.value, onInput: (e: Event) => emit('update:value', (e.target as HTMLInputElement).value) }) },
  NSwitch: { props: ['value'], emits: ['update:value'], setup: (props: any, { emit }: any) => () => h('button', { onClick: () => emit('update:value', !props.value) }) },
  NSelect: { props: ['value', 'options'], emits: ['update:value'], setup: () => () => h('select') },
  NCheckboxGroup: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NCheckbox: { setup: () => () => h('input', { type: 'checkbox' }) },
  NButton: { emits: ['click'], setup: (_p: any, { slots, emit, attrs }: any) => () => h('button', { ...attrs, onClick: () => emit('click') }, slots.default?.()) },
  NSpace: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  NTag: { setup: (_p: any, { slots }: any) => () => h('span', slots.default?.()) },
  NAlert: { setup: (_p: any, { slots }: any) => () => h('div', slots.default?.()) },
  useMessage: () => ({ success: vi.fn(), error: vi.fn() })
}))

describe('MattermostNotificationsPanel', () => {
  const config = {
    integration: { mattermost_server_url: 'https://mattermost.example.com', mattermost_bot_token_configured: true },
    profiles: [
      { id: 1, name: 'Team alerts', enabled: true, target_type: 'channel', team_name: 'core', channel_name: 'alerts', mention_in_channel: true, send_for_manual_tasks: true, event_types: ['task_completed'], field_keys: ['task_id'] }
    ]
  }

  beforeEach(() => {
    vi.clearAllMocks()
    mockApi.getMattermostNotificationConfig.mockResolvedValue(config)
  })

  it('opens create modal with default profile form', async () => {
    const wrapper = mount(MattermostNotificationsPanel, { props: { isMobile: false, reloadKey: 0 } })
    await vi.waitFor(() => expect(mockApi.getMattermostNotificationConfig).toHaveBeenCalled())

    wrapper.vm.openCreateProfileModal()

    expect(wrapper.vm.profileModalVisible).toBe(true)
    expect(wrapper.vm.editingProfileId).toBeNull()
    expect(wrapper.find('[data-testid="notification-profile-modal"]').exists()).toBe(true)
  })

  it('resets edit state when closing modal', async () => {
    const wrapper = mount(MattermostNotificationsPanel, { props: { isMobile: false, reloadKey: 0 } })
    await vi.waitFor(() => expect(mockApi.getMattermostNotificationConfig).toHaveBeenCalled())

    wrapper.vm.openEditProfileModal(config.profiles[0])
    wrapper.vm.closeProfileModal()

    expect(wrapper.vm.profileModalVisible).toBe(false)
    expect(wrapper.vm.editingProfileId).toBeNull()
    expect(wrapper.vm.profileForm.name).toBe('')
  })
})
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd frontend && npx vitest run src/components/config/MattermostNotificationsPanel.spec.ts`

Expected: FAIL because `closeProfileModal()` does not exist and modal close currently does not reset edit state.

- [ ] **Step 3: Add an explicit close/reset helper**

In `frontend/src/components/config/MattermostNotificationsPanel.vue`, add:

```ts
function resetProfileForm() {
  editingProfileId.value = null
  Object.assign(profileForm, createEmptyProfileForm())
}

function closeProfileModal() {
  profileModalVisible.value = false
  resetProfileForm()
}

function openCreateProfileModal() {
  resetProfileForm()
  profileModalVisible.value = true
}

function openEditProfileModal(profile: MattermostNotificationProfile) {
  editingProfileId.value = profile.id
  Object.assign(profileForm, {
    name: profile.name,
    enabled: profile.enabled,
    target_type: profile.target_type,
    team_name: profile.team_name || '',
    channel_name: profile.channel_name || '',
    mention_in_channel: profile.mention_in_channel,
    send_for_manual_tasks: profile.send_for_manual_tasks,
    event_types: [...profile.event_types],
    field_keys: [...profile.field_keys]
  })
  profileModalVisible.value = true
}
```

Update the modal footer cancel button:

```vue
<n-button secondary :disabled="profileSaving" @click="closeProfileModal">
  {{ t('common.cancel') }}
</n-button>
```

And after a successful save:

```ts
    closeProfileModal()
    await fetchNotifications(false)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `cd frontend && npx vitest run src/components/config/MattermostNotificationsPanel.spec.ts`

Expected: PASS with 2 passing tests.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config/MattermostNotificationsPanel.vue frontend/src/components/config/MattermostNotificationsPanel.spec.ts
git commit -m "test: cover notification profile modal reset flow"
```

---

### Task 4: Verify the config-page modal unification end to end

**Files:**
- Verify: `frontend/src/components/config/AIProvidersPanel.vue`
- Verify: `frontend/src/views/config/PromptTemplatesPanel.vue`
- Verify: `frontend/src/components/config/MattermostNotificationsPanel.vue`
- Verify: `frontend/src/views/Config.spec.ts`

- [ ] **Step 1: Run targeted frontend tests**

Run:

```bash
cd frontend && npx vitest run \
  src/components/config/AIProvidersPanel.spec.ts \
  src/views/config/PromptTemplatesPanel.spec.ts \
  src/components/config/MattermostNotificationsPanel.spec.ts \
  src/views/Config.spec.ts
```

Expected: PASS for all targeted config-page tests.

- [ ] **Step 2: Fix any test-coupling fallout in `Config.spec.ts` if needed**

If `Config.spec.ts` fails because a panel stub or import expectation changed, keep the fix minimal:

```ts
const globalStubs = {
  RuntimeSettingsPanel: { template: '<div class="runtime-panel">Runtime</div>' },
  GitLabSettingsPanel: {
    template: '<div class="gitlab-panel">GitLab</div>',
    methods: { fetchWebhookStatuses: () => {} }
  },
  AuthSettingsPanel: { template: '<div class="auth-panel">Auth</div>' },
  MaintenancePanel: { template: '<div class="maintenance-panel">Maintenance</div>' },
  PromptTemplatesPanel: {
    template: '<div class="prompt-panel">Prompts</div>',
    methods: { fetchPromptTemplates: () => {} }
  },
  MattermostNotificationsPanel: { template: '<div class="mattermost-panel">Mattermost</div>' },
  WorkerSettingsPanel: { template: '<div class="worker-panel">Worker</div>' },
  AIProvidersPanel: { template: '<div class="ai-providers-panel">AI Providers</div>' },
  WebhookEventsPanel: { template: '<div class="webhook-events-panel">Webhook Events</div>' }
}
```

The point of this step is not to change parent behavior — only to keep parent tests compatible with the new panel-level unit coverage.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm run build`

Expected: Vite build completes successfully with no TypeScript errors from the modal refactor.

- [ ] **Step 4: Commit final verification or compatibility fix**

```bash
git add frontend/src/views/Config.spec.ts
git commit -m "test: verify config modal unification"
```

---

## Self-Review Checklist

- Spec coverage:
  - AI Providers drawer → modal: covered by Task 1
  - Prompt Templates inline editor → modal: covered by Task 2
  - Mattermost profile modal alignment: covered by Task 3
  - Frontend tests/build verification: covered by Task 4
- Placeholder scan:
  - No TODO/TBD markers
  - Every code-changing step includes explicit code
  - Every verification step includes an exact command
- Type consistency:
  - AI Providers uses `modalVisible`
  - Prompt Templates uses `promptTemplateModalVisible`
  - Mattermost uses `closeProfileModal()` + `resetProfileForm()`

## Execution Notes

- Keep commit scope tight per task.
- Do not widen scope into a shared modal abstraction.
- Reuse existing i18n keys unless a modal-specific label is strictly necessary.
- If a commit is created by the implementing agent, include the required Co-authored-by trailer.
