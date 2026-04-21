<template>
  <div class="create-task-page" data-testid="create-task-page">
    <n-space vertical :size="16">
      <PageHeader
        data-testid="create-task-header"
        root-class="create-task-page__hero"
        title-class="create-task-page__title"
        subtitle-class="create-task-page__subtitle"
        actions-class="create-task-page__actions"
        :title="t('createTask.title')"
        :subtitle="t('createTask.subtitle')"
      >
        <template #actions>
          <n-space :size="8" wrap class="create-task-page__tags">
            <n-tag size="small" round type="info">{{ t('createTask.manualTrigger') }}</n-tag>
            <n-tag size="small" round>{{ t('createTask.schedulerAware') }}</n-tag>
            <n-tag size="small" round>{{ t('createTask.issueDriven') }}</n-tag>
          </n-space>
        </template>
      </PageHeader>

      <n-card class="create-task-card" :bordered="false" data-testid="create-task-card">
        <template #header>
          <div class="create-task-card__header">
            <div>
              <div class="create-task-card__title">{{ t('createTask.taskDetails') }}</div>
              <div class="create-task-card__subtitle">{{ t('createTask.taskDetailsSubtitle') }}</div>
            </div>
          </div>
        </template>
        <n-spin :show="loading">
          <n-form
            :key="formResetKey"
            ref="formRef"
            :model="formValue"
            :rules="rules"
            label-placement="top"
            class="create-task-form"
            data-testid="create-task-form"
          >
            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.issueSelection') }}</div>
              <n-form-item :label="t('createTask.issue')" path="issue_id">
                <n-select
                  data-testid="create-task-issue-select"
                  v-model:value="formValue.issue_id"
                  :options="issueOptions"
                  :loading="issuesLoading"
                  filterable
                  :placeholder="t('createTask.selectIssue')"
                  @update:value="handleIssueChange"
                />
              </n-form-item>
              <div v-if="selectedIssue" class="issue-context" data-testid="create-task-issue-context">
                <div class="issue-context__title">{{ selectedIssue.title }}</div>
                <div class="issue-context__meta">
                  <span v-if="selectedIssue.project_id" class="issue-context__item">
                    <span class="issue-context__label">{{ t('createTask.project') }}:</span>
                    #{{ selectedIssue.project_id }}
                  </span>
                  <span v-if="selectedIssue.branch_name" class="issue-context__item">
                    <span class="issue-context__label">{{ t('createTask.branch') }}:</span>
                    {{ selectedIssue.branch_name }}
                  </span>
                  <span v-if="selectedIssue.base_branch" class="issue-context__item">
                    <span class="issue-context__label">{{ t('createTask.baseBranch') }}:</span>
                    {{ selectedIssue.base_branch }}
                  </span>
                  <span v-if="selectedIssue.target_branch" class="issue-context__item">
                    <span class="issue-context__label">{{ t('createTask.targetBranch') }}:</span>
                    {{ selectedIssue.target_branch }}
                  </span>
                  <span class="issue-context__item">
                    <span class="issue-context__label">{{ t('common.status') }}:</span>
                    <n-tag size="tiny" :type="selectedIssue.status === 'open' ? 'info' : selectedIssue.status === 'in_progress' ? 'warning' : 'success'">
                      {{ selectedIssue.status }}
                    </n-tag>
                  </span>
                </div>
                <div v-if="selectedIssue.description" class="issue-context__description">
                  {{ selectedIssue.description }}
                </div>
              </div>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.implementationPrompt') }}</div>
              <div class="prompt-label-row">
                <span class="prompt-label">{{ t('createTask.prompt') }}<span class="prompt-label__required">*</span></span>
                <n-button
                      size="small"
                      :disabled="promptTemplatesLoading || promptTemplates.length === 0"
                      :loading="promptTemplatesLoading"
                      type="default"
                      @click="showTemplateDrawer = true"
                    >
                      <template #icon>
                        <n-icon :component="DocumentTextOutline" />
                      </template>
                      {{ t('createTask.useTemplate') }}
                    </n-button>
              </div>
              <n-form-item path="user_prompt" :show-label="false">
                <VariableEditor
                  data-testid="create-task-prompt-editor"
                  v-model="formValue.user_prompt"
                  :variable-tips="promptVariableTips"
                />
                <template #feedback>
                  <div v-if="unreplacedVariables.length > 0" class="prompt-variable-warning">
                    <n-icon :component="WarningOutline" size="14" />
                    <span>{{ t('createTask.unreplacedVariablesHint') }}: {{ unreplacedVariables.join(', ') }}</span>
                  </div>
                </template>
              </n-form-item>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.prioritySchedule') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('common.priority')" path="priority">
                    <n-radio-group v-model:value="formValue.priority" class="priority-selector" data-testid="create-task-priority-group">
                      <div
                        v-for="opt in priorityOptions"
                        :key="opt.value"
                        class="priority-card"
                        :class="[`priority-card--p${opt.value}`, { 'priority-card--active': formValue.priority === opt.value }]"
                        @click="formValue.priority = opt.value"
                      >
                        <n-radio :value="opt.value" class="priority-card__radio" />
                        <div class="priority-card__text">
                          <div class="priority-card__label">{{ opt.label }}</div>
                          <div class="priority-card__desc">{{ opt.desc }}</div>
                        </div>
                      </div>
                    </n-radio-group>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('createTask.schedule')" path="schedule_type">
                    <n-space vertical :size="10" style="width: 100%">
                        <n-radio-group
                          v-model:value="scheduleType"
                          name="scheduleType"
                          data-testid="create-task-schedule-group"
                        >
                        <n-space vertical :size="8">
                          <n-radio value="now">{{ t('createTask.executeNow') }}</n-radio>
                          <n-radio value="delay">{{ t('createTask.delay') }}</n-radio>
                          <n-radio value="scheduled">{{ t('createTask.scheduleAt') }}</n-radio>
                        </n-space>
                      </n-radio-group>

                      <n-space v-if="scheduleType === 'delay'" align="center" wrap>
                        <n-input-number
                          v-model:value="delayValue"
                          :min="1"
                          :max="86400"
                          style="width: 120px"
                        />
                        <n-select
                          v-model:value="delayUnit"
                          :options="[
                            { label: t('createTask.delaySeconds'), value: 'seconds' },
                            { label: t('createTask.delayMinutes'), value: 'minutes' },
                            { label: t('createTask.delayHours'), value: 'hours' }
                          ]"
                          style="width: 140px"
                        />
                      </n-space>

                        <n-date-picker
                          v-if="scheduleType === 'scheduled'"
                          v-model:value="scheduledDatetime"
                          type="datetime"
                          class="content-width-datetime-picker"
                          :placeholder="t('createTask.selectDateTime')"
                          :is-date-disabled="isScheduledDateDisabled"
                          :is-time-disabled="isScheduledTimeDisabled"
                          :status="scheduledDatetimeError ? 'error' : undefined"
                       />
                       <div v-if="scheduleType === 'scheduled' && scheduledDatetimeError" class="create-task-form__schedule-error">
                         {{ scheduledDatetimeError }}
                       </div>


                       <!-- Heatmap trigger: shown for both delay and scheduled modes -->
                       <n-button
                         v-if="scheduleType === 'delay' || scheduleType === 'scheduled'"
                         size="small"
                         secondary
                         :loading="scheduledTasksLoading"
                         @click="openScheduleDrawer"
                       >
                         <template #icon><n-icon :component="CalendarOutline" /></template>
                         {{ t('createTask.viewScheduleHeatmap') }}
                       </n-button>

                       <n-alert
                         v-if="slotCapacity?.is_full"
                         :type="slotCapacity.enforce ? 'error' : 'warning'"
                         class="slot-warning"
                         style="margin-top: 8px;"
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

                      <div class="create-task-form__hint">
                        {{ scheduleSummary }}
                      </div>
                    </n-space>
                  </n-form-item>
                </n-gi>

                <n-gi :span="isMobile ? 1 : 2">
                  <n-form-item :label="t('config.providers.providerLabel')">
                    <n-select
                      v-model:value="selectedProviderId"
                      :options="providerOptions"
                      clearable
                      :placeholder="t('config.providers.systemDefault')"
                    />
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-task-form__actions">
               <n-space justify="end" wrap data-testid="create-task-form-actions">
                 <n-button secondary strong round data-testid="create-task-reset-button" @click="handleReset">
                  {{ t('common.reset') }}
                 </n-button>
                 <n-button
                   type="primary"
                   strong
                   round
                   data-testid="create-task-submit-button"
                   @click="handleSubmit"
                   :loading="submitting"
                   :disabled="submitting || slotCapacityLoading || (slotCapacity?.is_full && slotCapacity?.enforce)"
                 >
                   {{ t('common.createTask') }}
                 </n-button>
               </n-space>
            </div>
          </n-form>
        </n-spin>
      </n-card>

      <!-- Success Dialog -->
      <n-modal v-model:show="showSuccessModal" preset="dialog" :title="t('createTask.successTitle')">
        <n-space vertical>
          <p>{{ t('createTask.successMessage', { id: createdTaskId }) }}</p>
          <n-space>
            <n-button @click="viewTask">{{ t('common.viewTask') }}</n-button>
            <n-button type="primary" @click="createAnother">{{ t('common.createAnother') }}</n-button>
          </n-space>
        </n-space>
      </n-modal>

      <!-- Schedule Heatmap Drawer -->
      <n-drawer v-model:show="showScheduleDrawer" :width="isMobile ? '100%' : 580" placement="right">
        <n-drawer-content :title="t('createTask.schedulePreviewTitle')" closable>
          <n-spin v-if="scheduledTasksLoading" :description="t('createTask.schedulePreviewLoading')" />
          <template v-else>
            <p class="schedule-drawer__hint">{{ t('createTask.schedulePreviewHint') }}</p>
            <HeatmapChart
              :tasks="scheduledTasksForPreview"
              :selected-ms="heatmapSelectedMs"
              :max-per-slot="slotMaxTasks"
              :enforce-capacity="slotEnforce"
              @cell-click="handleScheduleHeatmapCellClick"
            />
          </template>
        </n-drawer-content>
      </n-drawer>

      <!-- Template Picker Drawer -->
      <n-drawer v-model:show="showTemplateDrawer" :width="isMobile ? '100%' : 480" placement="right">
        <n-drawer-content :title="t('createTask.selectTemplate')" closable>
          <div style="overflow-y: auto;">
            <div v-if="promptTemplates.length === 0" class="prompt-template-dropdown__empty">
              {{ t('createTask.noPromptTemplates') }}
            </div>
            <div
              v-for="tmpl in promptTemplates"
              :key="tmpl.id"
              class="prompt-template-dropdown__item"
              @click="applyPromptTemplate(tmpl); showTemplateDrawer = false"
            >
              <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
              <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 80) }}...</div>
            </div>
          </div>
        </n-drawer-content>
      </n-drawer>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NForm, NFormItem, NSelect, NInputNumber,
  NButton, NSpin, NSpace, NRadioGroup, NRadio, NModal,
  NDatePicker, NTag, NGrid, NGi, NIcon,
  NDrawer, NDrawerContent, NAlert,
  useMessage, FormInst, FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { createTask, getIssues, getPromptTemplates, getScheduledTasks, getSlotCapacity, getConfig, getProviders, type Issue, type CreateTaskRequest, type PromptTemplate, type Task, type SlotCapacityInfo, type AIProvider } from '../api'
import { formatDateTimeUtc8, formatDateTimeUtc8Compact, formatTimeUtc8 } from '../utils/datetime'
import { isSameLocalDay } from '../utils/format'
import { extractSlotErrorMessage } from '../utils/slotError'
import { DocumentTextOutline, WarningOutline, CalendarOutline } from '@vicons/ionicons5'
import PageHeader from '../components/PageHeader.vue'
import VariableEditor from '../components/VariableEditor.vue'
import HeatmapChart from '../components/HeatmapChart.vue'
import { useBreakpoints } from '../composables/useBreakpoints'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

// Loading states
const loading = ref(false)
const issuesLoading = ref(false)
const submitting = ref(false)
const promptTemplatesLoading = ref(false)

// Data
const issues = ref<Issue[]>([])
const promptTemplates = ref<PromptTemplate[]>([])
const providers = ref<AIProvider[]>([])
const selectedProviderId = ref<number | null>(null)

// Per-session variable tips from template (not persisted)
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)

// Detect unreplaced variables in prompt
const unreplacedVariables = computed(() => {
  const content = formValue.value.user_prompt || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

const providerOptions = computed(() =>
  providers.value.map(p => ({
    label: `${p.name} (${p.model})${p.is_default ? ' ★' : ''}`,
    value: p.id,
  }))
)

const priorityOptions = computed(() => [
  { value: 0, label: t('createTask.p0'), desc: t('createTask.p0Desc') },
  { value: 1, label: t('createTask.p1'), desc: t('createTask.p1Desc') },
  { value: 2, label: t('createTask.p2'), desc: t('createTask.p2Desc') },
])

// Form state
const formRef = ref<FormInst | null>(null)
const formResetKey = ref(0)

interface FormModel {
  issue_id: number | null
  user_prompt: string
  priority: number
  delay_seconds?: number
  scheduled_datetime?: string
}

function createInitialFormValue(): FormModel {
  return {
    issue_id: null,
    user_prompt: '',
    priority: 1,
    delay_seconds: undefined,
    scheduled_datetime: undefined
  }
}

const formValue = ref<FormModel>(createInitialFormValue())

// UI state
const scheduleType = ref<'now' | 'delay' | 'scheduled'>('now')
const delayValue = ref(5)
const delayUnit = ref<'seconds' | 'minutes' | 'hours'>('minutes')
const scheduledDatetime = ref<number | null>(null)
const scheduledDatetimeError = ref<string | null>(null)

watch(scheduledDatetime, (val) => {
  if (val !== null && val <= Date.now()) {
    scheduledDatetimeError.value = t('createTask.scheduledTimePast')
  } else {
    scheduledDatetimeError.value = null
  }
})

const scheduledTasksForPreview = ref<Task[]>([])
const scheduledTasksLoading = ref(false)
const showScheduleDrawer = ref(false)

// Slot capacity
const slotCapacity = ref<SlotCapacityInfo | null>(null)
const slotCapacityLoading = ref(false)
const slotMaxTasks = ref(0)
const slotEnforce = ref(false)
let slotCheckTimeout: ReturnType<typeof setTimeout> | undefined
let slotCheckGeneration = 0

function checkSlotCapacity() {
  slotCapacity.value = null
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++

  const ms = heatmapSelectedMs.value
  if (!ms) return

  const currentGeneration = slotCheckGeneration
  slotCheckTimeout = setTimeout(async () => {
    slotCapacityLoading.value = true
    try {
      const scheduledAt = new Date(ms).toISOString()
      const result = await getSlotCapacity(scheduledAt)
      if (currentGeneration !== slotCheckGeneration) return
      slotCapacity.value = result
    } catch {
      if (currentGeneration !== slotCheckGeneration) return
      slotCapacity.value = null
    } finally {
      if (currentGeneration === slotCheckGeneration) {
        slotCapacityLoading.value = false
      }
    }
  }, 300)
}

onUnmounted(() => {
  if (slotCheckTimeout) clearTimeout(slotCheckTimeout)
  slotCheckGeneration++
})

const showTemplateDrawer = ref(false)

// Computed selected time for heatmap: works for both delay and scheduled modes
const heatmapSelectedMs = computed<number | null>(() => {
  if (scheduleType.value === 'scheduled') return scheduledDatetime.value
  if (scheduleType.value === 'delay') {
    const multiplier = delayUnit.value === 'seconds' ? 1000
      : delayUnit.value === 'minutes' ? 60 * 1000
      : 60 * 60 * 1000
    return Date.now() + delayValue.value * multiplier
  }
  return null
})

watch(heatmapSelectedMs, () => checkSlotCapacity())

// Success modal
const showSuccessModal = ref(false)
const createdTaskId = ref(0)

// Issue options for the select dropdown
const issueOptions = computed(() =>
  issues.value.map(issue => ({
    label: `#${issue.id} – ${issue.title}`,
    value: issue.id
  }))
)

// Currently selected issue (for displaying context info)
const selectedIssue = computed(() =>
  formValue.value.issue_id != null
    ? issues.value.find(i => i.id === formValue.value.issue_id) ?? null
    : null
)

const scheduleSummary = computed(() => {
  if (scheduleType.value === 'now') {
    return t('createTask.runsImmediately')
  }

  if (scheduleType.value === 'delay') {
    if (!delayValue.value || delayValue.value <= 0) {
      return t('createTask.delayGreaterThanZero')
    }
    const unitKey = delayUnit.value === 'seconds'
      ? 'createTask.delaySeconds'
      : delayUnit.value === 'minutes'
        ? 'createTask.delayMinutes'
        : 'createTask.delayHours'
    return t('createTask.taskWillRunAfter', { value: delayValue.value, unit: t(unitKey) })
  }

  if (!scheduledDatetime.value) {
    return t('createTask.selectFutureTime')
  }

  return t('createTask.taskWillRunAt', { time: formatDateTimeUtc8(scheduledDatetime.value) })
})

function isScheduledDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()

  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)

  return candidate.getTime() < today.getTime()
}

function isScheduledTimeDisabled(timestamp: number) {
  const selectedDate = new Date(timestamp)
  const now = new Date()

  if (!isSameLocalDay(selectedDate, now)) {
    return {}
  }

  const currentHour = now.getHours()
  const currentMinute = now.getMinutes()
  const currentSecond = now.getSeconds()

  return {
    isHourDisabled: (hour: number) => hour < currentHour,
    isMinuteDisabled: (minute: number, hour: number | null) => (
      hour !== null
      && hour === currentHour
      && minute < currentMinute
    ),
    isSecondDisabled: (second: number, minute: number | null, hour: number | null) => (
      hour !== null
      && minute !== null
      && hour === currentHour
      && minute === currentMinute
      && second < currentSecond
    )
  }
}

async function openScheduleDrawer() {
  showScheduleDrawer.value = true
  if (scheduledTasksForPreview.value.length === 0) {
    scheduledTasksLoading.value = true
    try {
      scheduledTasksForPreview.value = await getScheduledTasks()
    } catch {
      scheduledTasksForPreview.value = []
    } finally {
      scheduledTasksLoading.value = false
    }
  }
  // Fetch slot config for heatmap display
  try {
    const config = await getConfig()
    slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
    slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
  } catch { /* ignore */ }
}

function handleScheduleHeatmapCellClick(startMs: number) {
  scheduledDatetime.value = startMs
  scheduleType.value = 'scheduled'
  showScheduleDrawer.value = false
}

// Validation rules
const rules: FormRules = {
  issue_id: {
    required: true,
    type: 'number',
    message: t('createTask.pleaseSelectIssue'),
    trigger: 'change'
  },
  user_prompt: {
    required: true,
    message: t('createTask.pleaseEnterPrompt'),
    trigger: 'blur'
  }
}

// Fetch issues
async function fetchIssues() {
  issuesLoading.value = true
  try {
    const response = await getIssues({ status: 'open', page_size: 100 })
    issues.value = response.items
  } catch (error) {
    message.error(t('createTask.failedToFetchIssues'))
  } finally {
    issuesLoading.value = false
  }
}

// Fetch prompt templates
async function fetchPromptTemplates() {
  promptTemplatesLoading.value = true
  try {
    promptTemplates.value = await getPromptTemplates()
  } catch (error) {
    console.error('Failed to fetch prompt templates:', error)
  } finally {
    promptTemplatesLoading.value = false
  }
}

// Apply prompt template
function applyPromptTemplate(template: PromptTemplate) {
  if (formValue.value.user_prompt && formValue.value.user_prompt.trim() !== '') {
    if (!confirm(t('createTask.confirmOverwritePrompt'))) {
      return
    }
  }
  formValue.value.user_prompt = template.content
  promptVariableTips.value = template.variable_tips
}

// Handle issue selection change
function handleIssueChange(_issueId: number | null) {
  // Selection itself is bound via v-model; no extra logic needed
}

async function handleReset() {
  Object.assign(formValue.value, createInitialFormValue())
  scheduleType.value = 'now'
  delayValue.value = 5
  delayUnit.value = 'minutes'
  scheduledDatetime.value = null
  selectedProviderId.value = null
  createdTaskId.value = 0
  formResetKey.value += 1

  await nextTick()
  formRef.value?.restoreValidation()
}

function buildScheduleRequest(): Pick<CreateTaskRequest, 'delay_seconds' | 'scheduled_datetime'> {
  if (scheduleType.value === 'delay') {
    if (delayValue.value === null || !Number.isFinite(delayValue.value) || delayValue.value <= 0) {
      throw new Error(t('createTask.invalidDelay'))
    }

    const multipliers: Record<'seconds' | 'minutes' | 'hours', number> = {
      seconds: 1,
      minutes: 60,
      hours: 3600
    }

    return {
      delay_seconds: Math.floor(delayValue.value * multipliers[delayUnit.value])
    }
  }

  if (scheduleType.value === 'scheduled') {
    if (!scheduledDatetime.value) {
      throw new Error(t('createTask.pleaseSelectScheduledTime'))
    }

    if (scheduledDatetime.value <= Date.now()) {
      throw new Error(t('createTask.scheduledTimeFuture'))
    }

    return {
      scheduled_datetime: new Date(scheduledDatetime.value).toISOString()
    }
  }

  return {}
}

async function handleSubmit() {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch (errors) {
    return
  }

  submitting.value = true

  try {
    if (formValue.value.issue_id == null) {
      message.error(t('createTask.pleaseSelectIssue'))
      return
    }

    const request: CreateTaskRequest = {
      issue_id: formValue.value.issue_id,
      user_prompt: formValue.value.user_prompt || undefined,
      priority: formValue.value.priority
    }

    Object.assign(request, buildScheduleRequest())

    if (selectedProviderId.value) {
      request.provider_id = selectedProviderId.value
    }

    const task = await createTask(request)
    createdTaskId.value = task.id
    showSuccessModal.value = true
  } catch (error: any) {
    message.error(extractSlotErrorMessage(error, t, 'createTask.failedToCreateTask'))
  } finally {
    submitting.value = false
  }
}

function viewTask() {
  showSuccessModal.value = false
  router.push(`/tasks/${createdTaskId.value}`)
}

function createAnother() {
  showSuccessModal.value = false
  scheduledTasksForPreview.value = []
  void handleReset()
}

onMounted(() => {
  fetchIssues()
  fetchPromptTemplates()
  getProviders().then(data => { providers.value = data }).catch(() => {})
})

watch(scheduleType, (newType) => {
  if (newType !== 'scheduled') {
    scheduledDatetime.value = null
    showScheduleDrawer.value = false
  }
})
</script>

<style scoped>
.create-task-page {
  max-width: var(--app-page-max-width);
}

.create-task-page__actions {
  display: inline-flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
}

.create-task-page__tags {
  justify-content: flex-end;
}

.create-task-card {
  border-radius: var(--app-card-radius);
}

.create-task-card__header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.create-task-card__title {
  font-size: 18px;
  font-weight: 600;
}

.create-task-card__subtitle {
  margin-top: 4px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.create-task-form__section + .create-task-form__section,
.create-task-form__actions {
  margin-top: 20px;
}

.create-task-form__actions {
  display: flex;
  justify-content: flex-end;
  padding-top: 20px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.create-task-form__actions :deep(.n-space) {
  justify-content: flex-end;
}

.create-task-form__section-title {
  margin-bottom: 12px;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.02em;
  color: rgba(15, 23, 42, 0.62);
  text-transform: uppercase;
}

.create-task-form__hint {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.64);
}

.content-width-datetime-picker {
  width: fit-content;
  max-width: 100%;
}

@media (max-width: 768px) {
  .create-task-page__actions {
    width: 100%;
    justify-content: flex-start;
  }

  .create-task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .create-task-page__tags {
    width: 100%;
    justify-content: flex-start;
  }

  .create-task-form__actions {
    justify-content: stretch;
  }

  .create-task-form__actions :deep(.n-space),
  .create-task-form__actions :deep(.n-space-item),
  .create-task-form__actions :deep(.n-button) {
    width: 100%;
  }
}

.prompt-form-item {
  position: relative;
}

.prompt-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}

.prompt-label {
  font-size: 14px;
  color: var(--n-label-text-color);
}

.prompt-label__required {
  color: var(--n-color-error);
  margin-left: 2px;
}

.prompt-template-dropdown {
  padding: 8px 0;
  max-height: 300px;
  overflow-y: auto;
}

.prompt-template-dropdown__header {
  padding: 0 12px 8px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.6);
  border-bottom: 1px solid rgba(0, 0, 0, 0.08);
  margin-bottom: 8px;
}

.prompt-template-dropdown__empty {
  padding: 16px;
  text-align: center;
  color: rgba(15, 23, 42, 0.4);
  font-size: 13px;
}

.prompt-template-dropdown__item {
  padding: 8px 12px;
  cursor: pointer;
  transition: background-color 0.15s;
}

.prompt-template-dropdown__item:hover {
  background-color: rgba(32, 128, 240, 0.08);
}

.prompt-template-dropdown__item-name {
  font-size: 13px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.9);
  margin-bottom: 2px;
}

.prompt-template-dropdown__item-preview {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.5);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 6px;
  color: #d97706;
  font-size: 12px;
  margin-top: 4px;
}

.issue-context {
  margin-top: 12px;
  padding: 14px 16px;
  border-radius: 10px;
  background: rgba(32, 128, 240, 0.04);
  border: 1px solid rgba(32, 128, 240, 0.12);
}

.issue-context__title {
  font-size: 14px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.88);
  margin-bottom: 8px;
  line-height: 1.4;
}

.issue-context__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  align-items: center;
}

.issue-context__item {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.68);
}

.issue-context__label {
  font-weight: 500;
  color: rgba(15, 23, 42, 0.52);
}

.issue-context__description {
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(32, 128, 240, 0.08);
  font-size: 12px;
  line-height: 1.55;
  color: rgba(15, 23, 42, 0.58);
  white-space: pre-wrap;
  max-height: 80px;
  overflow-y: auto;
}

.schedule-drawer__hint {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.55);
  margin-bottom: 16px;
  margin-top: 0;
}

.create-task-form__schedule-error {
  font-size: 12px;
  color: #d03050;
  margin-top: 2px;
}

.priority-selector {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.priority-card {
  --priority-card-accent: rgba(100, 116, 139, 0.9);
  --priority-card-accent-soft: rgba(148, 163, 184, 0.18);
  --priority-card-accent-border: rgba(97, 107, 120, 0.24);
  --priority-card-gradient-strong: rgba(148, 163, 184, 0.18);
  --priority-card-gradient-soft: rgba(148, 163, 184, 0.08);
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 11px 14px;
  max-width: 350px;
  border-radius: 12px;
  border: 1px solid rgba(97, 107, 121, 0.14);
  background: rgba(204, 213, 225, 0.1);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.4);
  cursor: pointer;
  transition: border-color 0.18s, background 0.18s, box-shadow 0.18s, transform 0.18s;
}

.priority-card:hover {
  border-color: var(--priority-card-accent-border, rgba(148, 163, 184, 0.2));
  background: rgba(148, 163, 184, 0.06);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.46),
    0 0 12px 1px var(--priority-card-accent-soft, rgba(148, 163, 184, 0.18)),
    0 0 24px 2px var(--priority-card-accent-soft, rgba(148, 163, 184, 0.10));
  transform: translateY(-1px);
}

.priority-card--active {
  border-color: var(--priority-card-accent-border);
  background: rgba(221, 226, 234, 0.1);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.52),
    0 0 0 1px var(--priority-card-accent-soft),
    0 0 14px 1px var(--priority-card-accent-soft);
}

.priority-card--active:hover {
  border-color: var(--priority-card-accent-border);
  background: rgba(148, 163, 184, 0.06);
  box-shadow:
    inset 0 0 0 1px rgba(255, 255, 255, 0.52),
    0 0 0 1px var(--priority-card-accent-soft),
    0 0 18px 2px var(--priority-card-accent-soft),
    0 0 32px 4px var(--priority-card-accent-soft);
}

.priority-card__radio {
  flex-shrink: 0;
  margin-top: 1px;
}

.priority-card--p0 {
  --priority-card-accent: #d03050;
  --priority-card-accent-soft: rgba(208, 48, 80, 0.14);
  --priority-card-accent-border: rgba(208, 48, 80, 0.28);
  --priority-card-gradient-strong: rgba(208, 48, 80, 0.22);
  --priority-card-gradient-soft: rgba(208, 48, 80, 0.08);
}

.priority-card--p1 {
  --priority-card-accent: #f0a020;
  --priority-card-accent-soft: rgba(240, 160, 32, 0.16);
  --priority-card-accent-border: rgba(240, 160, 32, 0.28);
  --priority-card-gradient-strong: rgba(245, 158, 11, 0.24);
  --priority-card-gradient-soft: rgba(245, 158, 11, 0.1);
}

.priority-card--p2 {
  --priority-card-accent: #18a058;
  --priority-card-accent-soft: rgba(24, 160, 88, 0.14);
  --priority-card-accent-border: rgba(24, 160, 88, 0.26);
  --priority-card-gradient-strong: rgba(24, 160, 88, 0.22);
  --priority-card-gradient-soft: rgba(24, 160, 88, 0.08);
}

.priority-card__text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.priority-card__label {
  font-size: 12px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.88);
  letter-spacing: 0.01em;
  line-height: 1.3;
}

.priority-card__desc {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.54);
  line-height: 1.4;
}
</style>
