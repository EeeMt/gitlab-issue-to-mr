<template>
  <!-- Template Picker Sub-Drawer -->
  <n-drawer v-model:show="showTemplateDrawer" :width="isMobile ? '100%' : 480" placement="right">
    <div class="template-drawer-layout">
      <div class="template-drawer-layout__header">
        <span class="template-drawer-layout__title">{{ t('createTask.selectTemplate') }}</span>
        <n-button quaternary circle @click="showTemplateDrawer = false">
          <template #icon><n-icon size="18"><CloseOutline /></n-icon></template>
        </n-button>
      </div>
      <Transition name="banner-slide">
        <div v-if="pendingTemplate" class="template-overwrite-banner">
          <span class="template-overwrite-banner__text">{{ t('createTask.templateOverwriteConfirm') }}</span>
          <div class="template-overwrite-banner__actions">
            <n-button size="small" @click="cancelTemplateOverwrite">{{ t('common.cancel') }}</n-button>
            <n-button size="small" type="primary" @click="confirmTemplateOverwrite">{{ t('common.confirm') }}</n-button>
          </div>
        </div>
      </Transition>
      <div class="template-drawer-layout__body">
        <div v-if="promptTemplates.length === 0" class="prompt-template-dropdown__empty">
          {{ t('createTask.noPromptTemplates') }}
        </div>
        <div
          v-for="tmpl in promptTemplates"
          :key="tmpl.id"
          class="prompt-template-dropdown__item"
          :class="{ 'prompt-template-dropdown__item--pending': pendingTemplate?.id === tmpl.id }"
          @click="handleTemplateItemClick(tmpl)"
        >
          <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
          <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 80) }}...</div>
        </div>
      </div>
    </div>
  </n-drawer>

  <!-- Schedule Heatmap Sub-Drawer (create mode only) -->
  <n-drawer v-if="mode === 'create'" v-model:show="showHeatmapDrawer" :width="isMobile ? '100%' : 580" placement="right">
    <n-drawer-content :title="t('createTask.schedulePreviewTitle')" closable>
      <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
      <template v-else>
        <p style="margin-bottom: 12px; color: var(--n-text-color-3); font-size: 13px;">
          {{ t('createTask.schedulePreviewHint') }}
        </p>
        <HeatmapChart
          :tasks="scheduledTasksForPreview"
          :selected-ms="scheduledAt"
          :max-per-slot="slotMaxTasks"
          :enforce-capacity="slotEnforce"
          @cell-click="handleHeatmapCellClick"
        />
      </template>
    </n-drawer-content>
  </n-drawer>

  <!-- Main Drawer -->
  <n-drawer v-model:show="showProxy" :width="isMobile ? '100%' : 640" placement="right" :data-testid="drawerTestId">
    <n-drawer-content
      :title="mode === 'edit' ? t('taskView.editTask') : t('issue.createTask')"
      closable
    >
      <n-form label-placement="top" class="task-form-drawer__form">
        <!-- Prompt + require changes -->
        <div class="prompt-form-section">
          <div class="prompt-section-header">
            <div class="prompt-label-left">
              <span class="prompt-section-label-text">{{ t('issue.prompt') }}</span>
              <n-button
                size="tiny"
                :disabled="promptTemplatesLoading || promptTemplates.length === 0"
                :loading="promptTemplatesLoading"
                type="primary"
                ghost
                @click="showTemplateDrawer = true"
              >
                <template #icon>
                  <n-icon :component="DocumentTextOutline" size="12" />
                </template>
                {{ t('createTask.useTemplate') }}
              </n-button>
            </div>
            <div class="prompt-label-right">
            </div>
          </div>
          <VariableEditor
            v-model="prompt"
            :variable-tips="promptVariableTips"
            :placeholder="placeholderText"
          />
          <div v-if="unreplacedVariables.length > 0" class="prompt-variable-warning">
            <n-icon :component="WarningOutline" size="14" />
            <span>{{ t('createTask.unreplacedVariablesHint') }}: {{ unreplacedVariables.join(', ') }}</span>
          </div>
        </div>

        <!-- Task mode + require changes -->
        <n-form-item
          class="task-mode-form-item"
          :validation-status="taskModeErrorVisible ? 'error' : undefined"
          :feedback="taskModeErrorVisible ? t('issue.taskModeRequiredFeedback') : undefined"
        >
          <template #label>
            <div class="task-mode-label-row">
              <span>{{ t('issue.taskMode') }}</span>
              <span class="task-mode-label-hint">{{ t('issue.taskModeManualHint') }}</span>
            </div>
          </template>
          <div class="task-mode-section">
            <div class="task-mode-selector" role="radiogroup" :aria-label="t('issue.taskMode')">
              <div
                class="task-mode-card"
                role="radio"
                tabindex="0"
                :aria-checked="taskMode === 'execute'"
                :class="{
                  'task-mode-card--active': taskMode === 'execute',
                  'task-mode-card--error': taskModeErrorVisible
                }"
                @click="selectTaskMode('execute')"
                @keydown.enter.prevent="selectTaskMode('execute')"
                @keydown.space.prevent="selectTaskMode('execute')"
              >
                <n-icon :component="CodeSlashOutline" size="18" class="task-mode-card__icon" />
                <div class="task-mode-card__body">
                  <div class="task-mode-card__label">{{ t('issue.taskModeExecute') }}</div>
                  <div class="task-mode-card__desc">{{ t('issue.taskModeExecuteDesc') }}</div>
                </div>
                <n-icon
                  v-if="taskMode === 'execute'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="task-mode-card__check"
                />
              </div>
              <div
                class="task-mode-card"
                role="radio"
                tabindex="0"
                :aria-checked="taskMode === 'plan'"
                :class="{
                  'task-mode-card--active': taskMode === 'plan',
                  'task-mode-card--error': taskModeErrorVisible
                }"
                @click="selectTaskMode('plan')"
                @keydown.enter.prevent="selectTaskMode('plan')"
                @keydown.space.prevent="selectTaskMode('plan')"
              >
                <n-icon :component="BulbOutline" size="18" class="task-mode-card__icon" />
                <div class="task-mode-card__body">
                  <div class="task-mode-card__label">{{ t('issue.taskModePlan') }}</div>
                  <div class="task-mode-card__desc">{{ t('issue.taskModePlanDesc') }}</div>
                </div>
                <n-icon
                  v-if="taskMode === 'plan'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="task-mode-card__check"
                />
              </div>
            </div>
            <div v-if="taskMode === 'execute'" class="require-changes-row">
              <span class="prompt-label-require-text">{{ t('issue.requireChanges') }}</span>
              <n-tooltip trigger="hover" placement="top" :style="{ maxWidth: '260px', fontSize: '12px' }">
                <template #trigger>
                  <n-icon :component="InformationCircleOutline" size="13" class="require-changes-info-icon" />
                </template>
                {{ t('issue.requireChangesHint') }}
              </n-tooltip>
              <n-switch v-model:value="requireChanges" size="small" />
            </div>
          </div>
        </n-form-item>

        <!-- Priority cards -->
        <n-form-item :label="t('common.priority')">
          <n-radio-group v-model:value="priority" class="priority-selector">
            <div
              v-for="opt in priorityOptions"
              :key="opt.value"
              class="priority-card"
              :class="[
                `priority-card--p${opt.value}`,
                { 'priority-card--active': priority === opt.value }
              ]"
              @click="priority = opt.value"
            >
              <n-radio :value="opt.value" />
              <div>
                <div class="priority-card__label">{{ opt.label }}</div>
                <div class="priority-card__desc">{{ opt.desc }}</div>
              </div>
            </div>
          </n-radio-group>
        </n-form-item>

        <!-- Schedule (create mode only) -->
        <n-form-item v-if="mode === 'create'" :label="t('createTask.schedule')">
          <div class="schedule-section">
            <n-radio-group v-model:value="scheduleType">
              <n-radio value="now">{{ t('createTask.executeNow') }}</n-radio>
              <n-radio value="scheduled">{{ t('createTask.scheduleAt') }}</n-radio>
            </n-radio-group>
            <div class="schedule-row" :class="{ 'schedule-row--hidden': scheduleType !== 'scheduled' }">
              <n-date-picker
                v-model:value="scheduledAt"
                type="datetime"
                clearable
                style="width: 200px; flex-shrink: 0"
                :is-date-disabled="isScheduleDateDisabled"
              />
              <n-button
                size="small"
                secondary
                :loading="scheduledTasksLoading"
                @click="openHeatmapDrawer"
              >
                <template #icon><n-icon :component="CalendarOutline" /></template>
                {{ t('createTask.viewScheduleHeatmap') }}
              </n-button>
            </div>
          </div>
        </n-form-item>

        <!-- AI Provider -->
        <n-form-item :label="t('config.providers.providerLabel')">
          <n-select
            v-model:value="selectedProviderId"
            :options="providerOptions"
            clearable
            :placeholder="t('config.providers.systemDefault')"
          />
        </n-form-item>
      </n-form>

      <!-- Slot capacity alert (create mode only) -->
      <n-alert
        v-if="mode === 'create' && slotCapacity?.is_full"
        :type="slotCapacity.enforce ? 'error' : 'warning'"
        style="margin-bottom: 16px;"
      >
        {{ slotCapacity.enforce
          ? t('createTask.slotFullError', {
              start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
              end: formatTimeUtc8(slotCapacity.hour_end),
              count: slotCapacity.count,
              max: slotCapacity.max
            })
          : t('createTask.slotFullWarning', {
              start: formatDateTimeUtc8Compact(slotCapacity.hour_start),
              end: formatTimeUtc8(slotCapacity.hour_end),
              count: slotCapacity.count,
              max: slotCapacity.max
            })
        }}
      </n-alert>

      <!-- Usage limit alert (create mode only) -->
      <n-alert
        v-if="mode === 'create' && usageLimitDetail"
        type="warning"
        style="margin-bottom: 16px;"
        data-testid="issue-create-task-usage-alert"
      >
        <div class="task-form-drawer__usage-limit-alert">
          <div class="task-form-drawer__usage-limit-title">{{ t('createTask.usageLimitExceededTitle') }}</div>
          <div
            v-for="item in usageLimitDetail.exceeded_items"
            :key="`${item.field}-${item.reset_at}`"
            class="task-form-drawer__usage-limit-row"
          >
            <span>{{ t(`createTask.usageWindow.${item.window}`) }}</span>
            <span>{{ t(`createTask.usageMetric.${item.metric}`) }}</span>
            <span>{{ t('createTask.usageLimitUsed') }} {{ item.used }}/{{ item.limit }}</span>
            <span>{{ t('createTask.usageLimitReset') }} {{ formatUsageResetAt(item.reset_at) }}</span>
          </div>
        </div>
      </n-alert>

      <template #footer>
        <div style="display: flex; justify-content: flex-end;">
          <n-button
            type="primary"
            :loading="submitLoading"
            :data-testid="mode === 'create' ? 'issue-create-task-button' : 'task-form-save-button'"
            @click="mode === 'create' ? handleCreate() : handleEdit()"
          >
            {{ mode === 'create' ? t('issue.createTask') : t('common.save') }}
          </n-button>
        </div>
      </template>
    </n-drawer-content>
  </n-drawer>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onUnmounted, useAttrs } from 'vue'
import {
  NButton, NDrawer, NDrawerContent, NForm, NFormItem, NRadio, NRadioGroup,
  NDatePicker, NSelect, NAlert, NTooltip, NSwitch, NSpin, NIcon,
  useMessage
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextOutline,
  WarningOutline,
  CalendarOutline,
  CloseOutline,
  InformationCircleOutline,
  CodeSlashOutline,
  BulbOutline,
  CheckmarkCircleOutline
} from '@vicons/ionicons5'
import VariableEditor from './VariableEditor.vue'
import HeatmapChart from './HeatmapChart.vue'
import {
  createTask, updateTask, getPromptTemplates, getProviders, getScheduledTasks, getSlotCapacity, getConfig,
  type Task, type PromptTemplate, type SlotCapacityInfo, type AIProvider, type UpdateTaskRequest
} from '../api'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, formatTimeUtc8 } from '../utils/datetime'
import { extractSlotErrorMessage } from '../utils/slotError'
import { formatUsageResetAt, isUsageLimitExceededDetail, type UsageLimitExceededDetail } from '../utils/usageLimits'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  show: boolean
  mode?: 'create' | 'edit'
  issueId?: number
  issueDescription?: string
  task?: Task
}>(), {
  mode: 'create'
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [task: Task]
  updated: [task: Task]
}>()

const { t } = useI18n()
const message = useMessage()
const { isMobile } = useBreakpoints()
const attrs = useAttrs()

const showProxy = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val)
})

const drawerTestId = computed(() => {
  const testId = attrs['data-testid']
  return typeof testId === 'string' ? testId : 'task-form-drawer'
})

// Form state
const prompt = ref('')
const priority = ref(1)
const requireChanges = ref(true)
const taskMode = ref<'execute' | 'plan' | null>(null)
const taskModeErrorVisible = ref(false)
const selectedProviderId = ref<number | null>(null)
const scheduleType = ref<'now' | 'scheduled'>('now')
const scheduledAt = ref<number | null>(null)
const submitLoading = ref(false)
const usageLimitDetail = ref<UsageLimitExceededDetail | null>(null)

// Template picker state
const showTemplateDrawer = ref(false)
const promptTemplates = ref<PromptTemplate[]>([])
const promptTemplatesLoading = ref(false)
const pendingTemplate = ref<PromptTemplate | null>(null)
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)

// Providers state
const providers = ref<AIProvider[]>([])

// Schedule heatmap state (create mode)
const showHeatmapDrawer = ref(false)
const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
const slotCapacity = ref<SlotCapacityInfo | null>(null)
const slotCapacityLoading = ref(false)
let slotCheckTimeout: ReturnType<typeof setTimeout> | undefined
let slotCheckGeneration = 0

const priorityOptions = [
  { label: 'P0', value: 0, desc: t('createTask.priorityP0Desc') },
  { label: 'P1', value: 1, desc: t('createTask.priorityP1Desc') },
  { label: 'P2', value: 2, desc: t('createTask.priorityP2Desc') }
]

const placeholderText = computed(() =>
  props.issueDescription || t('issue.promptPlaceholder')
)

const unreplacedVariables = computed(() => {
  const content = prompt.value || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

const hasExistingPrompt = computed(() => Boolean(prompt.value && prompt.value.trim()))

const selectableProviders = computed(() =>
  providers.value.filter((provider) => {
    if (!provider.is_disabled) return true
    return props.mode === 'edit' && provider.id === props.task?.provider_id
  })
)

const providerOptions = computed(() =>
  selectableProviders.value.map(p => ({
    label: `${p.name} (${p.model})${p.is_default ? ' ★' : ''}${p.is_disabled ? ` - ${t('config.providers.disabled')}` : ''}`,
    value: p.id,
    disabled: p.is_disabled,
  }))
)

// --- Watchers ---
watch(showTemplateDrawer, (val) => {
  if (!val) pendingTemplate.value = null
})

watch(scheduleType, (val) => {
  if (val === 'now') scheduledAt.value = null
})

watch(scheduledAt, () => {
  if (props.mode === 'create') checkSlotCapacity()
})

watch(taskMode, (val) => {
  if (val !== null) taskModeErrorVisible.value = false
})

watch(() => props.show, (val) => {
  if (val) {
    if (props.mode === 'edit' && props.task) {
      prompt.value = props.task.user_prompt ?? ''
      priority.value = props.task.priority ?? 1
      requireChanges.value = props.task.require_changes ?? true
      taskMode.value = (props.task.task_mode as 'execute' | 'plan') ?? 'execute'
      selectedProviderId.value = props.task.provider_id ?? null
    } else if (props.mode === 'create') {
      if (!prompt.value && props.issueDescription) {
        prompt.value = props.issueDescription
      }
      taskMode.value = null
      requireChanges.value = true
      scheduleType.value = 'now'
      scheduledAt.value = null
      void loadScheduleContext()
    }
    usageLimitDetail.value = null
    taskModeErrorVisible.value = false
  }
})

// --- Data loading ---
async function loadProviders() {
  try {
    providers.value = await getProviders()
  } catch { /* non-critical */ }
}

async function loadTemplates() {
  promptTemplatesLoading.value = true
  try {
    promptTemplates.value = await getPromptTemplates()
  } catch { /* non-critical */ } finally {
    promptTemplatesLoading.value = false
  }
}

async function loadScheduleContext() {
  scheduledTasksLoading.value = true
  try {
    scheduledTasksForPreview.value = await getScheduledTasks()
  } catch {
    scheduledTasksForPreview.value = []
  } finally {
    scheduledTasksLoading.value = false
  }
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
}

function checkSlotCapacity() {
  slotCapacity.value = null
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
  const ms = scheduledAt.value
  if (!ms) return
  const gen = slotCheckGeneration
  slotCheckTimeout = setTimeout(async () => {
    slotCapacityLoading.value = true
    try {
      const result = await getSlotCapacity(new Date(ms).toISOString())
      if (gen !== slotCheckGeneration) return
      slotCapacity.value = result
    } catch {
      if (gen !== slotCheckGeneration) return
      slotCapacity.value = null
    } finally {
      if (gen === slotCheckGeneration) slotCapacityLoading.value = false
    }
  }, 300)
}

async function openHeatmapDrawer() {
  showHeatmapDrawer.value = true
  if (scheduledTasksForPreview.value.length === 0) {
    await loadScheduleContext()
  }
}

function handleHeatmapCellClick(startMs: number) {
  scheduledAt.value = startMs
  showHeatmapDrawer.value = false
}

function selectTaskMode(mode: 'execute' | 'plan') {
  taskMode.value = mode
}

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

// --- Template actions ---
function applyPromptTemplate(tmpl: PromptTemplate) {
  prompt.value = tmpl.content
  if (tmpl.variable_tips) {
    promptVariableTips.value = tmpl.variable_tips
  }
}

function handleTemplateItemClick(tmpl: PromptTemplate) {
  if (!hasExistingPrompt.value) {
    applyPromptTemplate(tmpl)
    showTemplateDrawer.value = false
  } else {
    pendingTemplate.value = tmpl
  }
}

function confirmTemplateOverwrite() {
  if (pendingTemplate.value) {
    applyPromptTemplate(pendingTemplate.value)
    pendingTemplate.value = null
    showTemplateDrawer.value = false
  }
}

function cancelTemplateOverwrite() {
  pendingTemplate.value = null
}

// --- Submit actions ---
async function handleCreate() {
  if (taskMode.value === null) {
    taskModeErrorVisible.value = true
    message.warning(t('issue.pleaseSelectTaskMode'))
    return
  }
  if (scheduleType.value === 'scheduled') {
    if (!scheduledAt.value) {
      message.warning(t('createTask.pleaseSelectScheduledTime'))
      return
    }
    if (scheduledAt.value <= Date.now()) {
      message.warning(t('createTask.scheduledTimeFuture'))
      return
    }
  }

  submitLoading.value = true
  usageLimitDetail.value = null
  try {
    const req: Parameters<typeof createTask>[0] = {
      issue_id: props.issueId!,
      priority: priority.value,
      require_changes: taskMode.value === 'plan' ? false : requireChanges.value
    }
    if (taskMode.value !== null) req.task_mode = taskMode.value
    if (prompt.value.trim()) req.user_prompt = prompt.value.trim()
    if (scheduleType.value === 'scheduled' && scheduledAt.value) {
      req.scheduled_datetime = new Date(scheduledAt.value).toISOString()
    }
    const pid = selectedProviderId.value ?? providers.value.find(p => p.is_default && !p.is_disabled)?.id
    if (pid == null) {
      message.warning(t('config.providers.noEnabledProvider'))
      return
    }
    req.provider_id = pid
    const created = await createTask(req)
    message.success(t('issue.taskCreated'))
    prompt.value = ''
    scheduledAt.value = null
    selectedProviderId.value = null
    scheduleType.value = 'now'
    scheduledTasksForPreview.value = []
    emit('update:show', false)
    emit('created', created)
  } catch (error: unknown) {
    const anyError = error as { response?: { data?: { detail?: unknown } } }
    const detail = anyError?.response?.data?.detail
    if (isUsageLimitExceededDetail(detail)) {
      usageLimitDetail.value = detail
    } else {
      message.error(extractSlotErrorMessage(error, t, 'createTask.failedToCreateTask'))
    }
  } finally {
    submitLoading.value = false
  }
}

async function handleEdit() {
  if (!props.task) return
  const trimmedPrompt = prompt.value.trim()
  if (!trimmedPrompt) {
    message.warning(t('createTask.pleaseEnterPrompt'))
    return
  }
  // Build a partial payload: only include fields that actually changed.
  const orig = props.task
  const payload: UpdateTaskRequest = {}
  if (trimmedPrompt !== orig.user_prompt) payload.user_prompt = trimmedPrompt
  if (priority.value !== orig.priority) payload.priority = priority.value
  if ((selectedProviderId.value ?? null) !== (orig.provider_id ?? null)) {
    payload.provider_id = selectedProviderId.value
  }
  if (requireChanges.value !== orig.require_changes) payload.require_changes = requireChanges.value
  if (taskMode.value !== null && taskMode.value !== (orig.task_mode ?? 'execute')) {
    payload.task_mode = taskMode.value
    // Switching to plan forces require_changes=false; switching back to execute
    // restores whatever the toggle says (already captured above if changed).
    if (taskMode.value === 'plan' && orig.require_changes !== false) {
      payload.require_changes = false
    }
  }

  if (Object.keys(payload).length === 0) {
    emit('update:show', false)
    return
  }
  submitLoading.value = true
  try {
    const updated = await updateTask(orig.id, payload)
    message.success(t('taskView.taskUpdated'))
    emit('update:show', false)
    emit('updated', updated)
  } catch (error: unknown) {
    const anyError = error as { response?: { data?: { detail?: unknown } } }
    const detail = anyError?.response?.data?.detail
    if (typeof detail === 'string') {
      message.error(detail)
    } else {
      message.error(t('taskView.failedToUpdateTask'))
    }
  } finally {
    submitLoading.value = false
  }
}

// --- Lifecycle ---
onMounted(() => {
  void loadProviders()
  void loadTemplates()
})

onUnmounted(() => {
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
})
</script>

<style scoped>
.task-form-drawer__form {
  max-width: 100%;
}

.task-form-drawer__form :deep(.variable-editor__codemirror .cm-editor) {
  min-height: 200px;
}

/* Prompt section */
.prompt-form-section {
  margin-bottom: 18px;
}

.prompt-section-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  min-width: 0;
  margin-bottom: 6px;
}

.prompt-section-label-text {
  font-size: 14px;
  color: var(--n-text-color);
}

.prompt-label-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.prompt-label-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.task-mode-label-row {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}

.task-mode-label-hint {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 400;
}

.task-mode-form-item :deep(.n-form-item-feedback-wrapper:not(:empty)) {
  margin-bottom: 8px;
}

.task-mode-form-item :deep(.n-form-item-feedback) {
  margin-bottom: 8px;
}

.task-mode-section {
  display: flex;
  flex-direction: column;
  width: 100%;
  gap: 0;
}

.task-mode-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}

:deep(.n-form-item-blank) {
  flex-direction: column;
  align-items: flex-start;
}

.task-mode-card {
  flex: 1;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  position: relative;
  padding: 10px 32px 10px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.task-mode-card:hover {
  border-color: var(--n-primary-color);
}

.task-mode-card--error {
  border-color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-card--error:hover {
  border-color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-card--active {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.06);
}

.task-mode-card__icon {
  margin-top: 2px;
  flex-shrink: 0;
  color: var(--n-text-color-3);
}

.task-mode-card--active .task-mode-card__icon {
  color: var(--n-primary-color);
}

.task-mode-card__check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--n-primary-color);
}

.task-mode-card__body {
  flex: 1;
  min-width: 0;
}

.task-mode-card__label {
  font-weight: 600;
  font-size: 13px;
}

.task-mode-card__desc {
  font-size: 11px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}

.require-changes-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-left: 12px;
}

.prompt-label-require-text {
  font-size: 12px;
  color: var(--n-label-text-color, #888);
}

.require-changes-info-icon {
  color: var(--n-label-text-color, #aaa);
  cursor: help;
  flex-shrink: 0;
}

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #f0a020;
  font-size: 12px;
  margin-top: 4px;
}

/* Priority selector */
.priority-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}

.priority-card {
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.15s;
}

.priority-card:hover {
  border-color: var(--n-primary-color);
}

.priority-card--active.priority-card--p0 {
  border-color: #e88080;
  background: rgba(232, 128, 128, 0.06);
}

.priority-card--active.priority-card--p1 {
  border-color: #f0a020;
  background: rgba(240, 160, 32, 0.06);
}

.priority-card--active.priority-card--p2 {
  border-color: #63e2b7;
  background: rgba(99, 226, 183, 0.06);
}

.priority-card--p0 .priority-card__label { color: #d03050; }
.priority-card--p1 .priority-card__label { color: #f0a020; }
.priority-card--p2 .priority-card__label { color: #18a058; }
.priority-card__label { font-weight: 600; font-size: 13px; }
.priority-card__desc { font-size: 11px; color: var(--n-text-color-3); }

/* Schedule section */
.schedule-section {
  display: flex;
  flex-direction: column;
  gap: 12px;
  width: 100%;
}

.schedule-row {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  overflow: hidden;
  max-height: 40px;
  opacity: 1;
  transition: max-height 0.2s ease, opacity 0.2s ease, margin 0.2s ease;
}

.schedule-row--hidden {
  max-height: 0;
  opacity: 0;
  margin: 0;
  pointer-events: none;
}

/* Template picker drawer */
.template-drawer-layout {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: var(--n-color, #fff);
}

.template-drawer-layout__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 20px;
  border-bottom: 1px solid rgba(0, 0, 0, 0.09);
  flex-shrink: 0;
}

.template-drawer-layout__title {
  font-size: 18px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.9);
}

.template-drawer-layout__body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
}

.prompt-template-dropdown__empty {
  padding: 16px;
  text-align: center;
  color: var(--n-text-color-3);
}

.prompt-template-dropdown__item {
  padding: 12px 16px;
  cursor: pointer;
  border-bottom: 1px solid rgba(128, 128, 128, 0.1);
}

.prompt-template-dropdown__item:hover {
  background: rgba(128, 128, 128, 0.05);
}

.prompt-template-dropdown__item--pending {
  background-color: rgba(32, 128, 240, 0.08);
  border-left: 3px solid #2080f0;
  padding-left: 9px;
}

.prompt-template-dropdown__item-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.prompt-template-dropdown__item-preview {
  font-size: 12px;
  color: var(--n-text-color-3);
}

.template-overwrite-banner {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 10px 14px;
  margin: 0 12px;
  background: rgba(255, 160, 32, 0.1);
  border: 1px solid rgba(255, 160, 32, 0.4);
  border-radius: 10px;
  flex-shrink: 0;
}

.banner-slide-enter-active,
.banner-slide-leave-active {
  transition: opacity 0.22s ease, transform 0.22s ease, max-height 0.22s ease, margin 0.22s ease, padding 0.22s ease;
  overflow: hidden;
  max-height: 80px;
}

.banner-slide-enter-from,
.banner-slide-leave-to {
  opacity: 0;
  transform: translateY(-6px);
  max-height: 0;
  margin-top: 0;
  margin-bottom: 0;
  padding-top: 0;
  padding-bottom: 0;
}

.template-overwrite-banner__text {
  flex: 1;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.82);
}

.template-overwrite-banner__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* Usage limit */
.task-form-drawer__usage-limit-alert {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.task-form-drawer__usage-limit-row {
  display: flex;
  gap: 8px;
  font-size: 13px;
  flex-wrap: wrap;
}
</style>
