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
            <n-tag size="small" round>{{ t('createTask.gitlabBranchWorkflow') }}</n-tag>
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
              <div class="create-task-form__section-title">{{ t('createTask.repositoryBranches') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('createTask.project')" path="project_id">
                      <n-select
                        data-testid="create-task-project-select"
                        v-model:value="formValue.project_id"
                      :options="projectOptions"
                      :loading="projectsLoading"
                      :placeholder="t('createTask.selectProject')"
                      @update:value="handleProjectChange"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('createTask.baseBranch')" path="base_branch">
                      <n-select
                        data-testid="create-task-base-branch-select"
                        v-model:value="formValue.base_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      :placeholder="t('createTask.selectBaseBranch')"
                      :disabled="!formValue.project_id"
                      @update:value="handleBaseBranchChange"
                    />
                    <template #feedback>
                      {{ t('createTask.baseBranchHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('createTask.newBranchName')" path="new_branch_name">
                      <n-input
                        data-testid="create-task-new-branch-input"
                        v-model:value="formValue.new_branch_name"
                      :placeholder="t('createTask.newBranchPlaceholder')"
                      :disabled="!formValue.project_id || !formValue.base_branch"
                    />
                    <template #feedback>
                      {{ t('createTask.newBranchHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.mrSettings') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item path="create_mr">
                    <template #label>
                      <n-tooltip placement="top">
                        <template #trigger>
                          <span class="create-task-form__toggle-label">
                            {{ t('createTask.createMR') }}
                            <n-icon :component="InformationCircleOutline" size="14" class="create-task-form__toggle-label-icon" />
                          </span>
                        </template>
                        {{ t('createTask.createMRTooltip') }}
                      </n-tooltip>
                    </template>
                    <n-switch
                      v-model:value="createMR"
                      data-testid="create-task-create-mr-switch"
                      @update:value="handleCreateMRChange"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi v-if="createMR">
                  <n-form-item :label="t('createTask.targetBranch')" path="target_branch">
                      <n-select
                        data-testid="create-task-target-branch-select"
                        v-model:value="formValue.target_branch"
                      :options="targetBranchOptions"
                      :disabled="!formValue.project_id"
                      :placeholder="t('createTask.selectTargetBranch')"
                    />
                    <template #feedback>
                      {{ t('createTask.targetBranchHint') }}
                    </template>
                  </n-form-item>
                  <div v-if="sameBranchConflict" class="create-task-form__warning">
                    {{ t('createTask.branchConflict') }}
                  </div>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.implementationPrompt') }}</div>
              <div class="prompt-label-row">
                <span class="prompt-label">{{ t('createTask.prompt') }}<span class="prompt-label__required">*</span></span>
                <n-popover trigger="click" placement="bottom-end" :width="300" :keep-alive-on-hover="false">
                  <template #trigger>
                    <n-button
                      size="small"
                      :disabled="promptTemplatesLoading || promptTemplates.length === 0"
                      :loading="promptTemplatesLoading"
                      type="default"
                    >
                      <template #icon>
                        <n-icon :component="DocumentTextOutline" />
                      </template>
                      {{ t('createTask.useTemplate') }}
                    </n-button>
                  </template>
                  <div class="prompt-template-dropdown">
                    <div class="prompt-template-dropdown__header">{{ t('createTask.selectPromptTemplate') }}</div>
                    <div v-if="promptTemplates.length === 0" class="prompt-template-dropdown__empty">
                      {{ t('createTask.noPromptTemplates') }}
                    </div>
                    <div
                      v-for="tmpl in promptTemplates"
                      :key="tmpl.id"
                      class="prompt-template-dropdown__item"
                      @click="applyPromptTemplate(tmpl)"
                    >
                      <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
                      <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 50) }}...</div>
                    </div>
                  </div>
                </n-popover>
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
                    <n-radio-group v-model:value="formValue.priority" data-testid="create-task-priority-group" style="display:flex; gap:8px;">
                      <n-radio-button :value="0" class="priority-btn priority-btn--p0">
                        <span class="priority-btn__dot"></span>{{ t('createTask.p0') }}
                      </n-radio-button>
                      <n-radio-button :value="1" class="priority-btn priority-btn--p1">
                        <span class="priority-btn__dot"></span>{{ t('createTask.p1') }}
                      </n-radio-button>
                      <n-radio-button :value="2" class="priority-btn priority-btn--p2">
                        <span class="priority-btn__dot"></span>{{ t('createTask.p2') }}
                      </n-radio-button>
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

                      <div class="create-task-form__hint">
                        {{ scheduleSummary }}
                      </div>
                    </n-space>
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
              @cell-click="handleScheduleHeatmapCellClick"
            />
          </template>
        </n-drawer-content>
      </n-drawer>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NForm, NFormItem, NSelect, NInput, NInputNumber,
  NButton, NSpin, NSpace, NRadioGroup, NRadio, NRadioButton, NModal,
  NDatePicker, NTag, NGrid, NGi, NPopover, NIcon, NSwitch, NTooltip,
  NDrawer, NDrawerContent,
  useMessage, FormInst, FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { getProjects, getBranches, createTask, getPromptTemplates, getScheduledTasks, type Project, type Branch, type CreateTaskRequest, type PromptTemplate, type Task } from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'
import { DocumentTextOutline, WarningOutline, InformationCircleOutline, CalendarOutline } from '@vicons/ionicons5'
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
const projectsLoading = ref(false)
const branchesLoading = ref(false)
const submitting = ref(false)
const promptTemplatesLoading = ref(false)

// Data
const projects = ref<Project[]>([])
const branches = ref<Branch[]>([])
const promptTemplates = ref<PromptTemplate[]>([])

// Per-session variable tips from template (not persisted)
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)

// Detect unreplaced variables in prompt
const unreplacedVariables = computed(() => {
  const content = formValue.value.user_prompt || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

// Form state
const formRef = ref<FormInst | null>(null)
const formResetKey = ref(0)

function createInitialFormValue(): CreateTaskRequest & { base_branch?: string; new_branch_name?: string; branch_name?: string } {
  return {
    project_id: undefined,
    base_branch: undefined,
    new_branch_name: '',
    branch_name: '',
    target_branch: 'main',
    user_prompt: '',
    priority: 0,
    delay_seconds: undefined,
    scheduled_datetime: undefined
  }
}

const formValue = ref<CreateTaskRequest & { base_branch?: string; new_branch_name?: string; branch_name?: string }>(createInitialFormValue())

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

// Create MR toggle
const createMR = ref(true)

// Success modal
const showSuccessModal = ref(false)
const createdTaskId = ref(0)

// Options
const projectOptions = computed(() =>
  projects.value.map(p => ({
    label: p.path_with_namespace,
    value: p.id
  }))
)

const branchOptions = computed(() =>
  branches.value.map(b => ({
    label: b.name,
    value: b.name
  }))
)

const targetBranchOptions = computed(() => {
  // Use branches for target, with 'main' as first option
  let options = branches.value.map(b => ({
    label: b.name,
    value: b.name
  }))

  // Move main to top if exists
  const mainIdx = options.findIndex(o => o.value === 'main')
  if (mainIdx > 0) {
    const main = options.splice(mainIdx, 1)[0]
    options.unshift(main)
  }

  return options
})

const resolvedSourceBranch = computed(() => {
  return (formValue.value.new_branch_name || '').trim()
})

const sameBranchConflict = computed(() => {
  return (
    !!resolvedSourceBranch.value &&
    !!formValue.value.target_branch &&
    resolvedSourceBranch.value === formValue.value.target_branch
  )
})

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

function isSameLocalDay(left: Date, right: Date): boolean {
  return (
    left.getFullYear() === right.getFullYear()
    && left.getMonth() === right.getMonth()
    && left.getDate() === right.getDate()
  )
}

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
}

function handleScheduleHeatmapCellClick(startMs: number) {
  scheduledDatetime.value = startMs
  scheduleType.value = 'scheduled'
  showScheduleDrawer.value = false
}

// Validation rules
const rules: FormRules = {
  project_id: {
    required: true,
    type: 'number',
    message: t('createTask.pleaseSelectProject'),
    trigger: 'change'
  },
  base_branch: {
    required: true,
    message: t('createTask.pleaseSelectBaseBranch'),
    trigger: 'change'
  },
  new_branch_name: {
    validator: () =>
      !sameBranchConflict.value || new Error(t('createTask.sourceTargetDifferent')),
    trigger: ['blur', 'input', 'change']
  },
  target_branch: {
    required: true,
    validator: () => {
      if (!createMR.value) return true
      if (!formValue.value.target_branch) {
        return new Error(t('createTask.pleaseSelectTargetBranch'))
      }
      return !sameBranchConflict.value || new Error(t('createTask.sourceTargetDifferent'))
    },
    trigger: ['blur', 'change', 'input']
  },
  user_prompt: {
    required: true,
    message: t('createTask.pleaseEnterPrompt'),
    trigger: 'blur'
  }
}

// Fetch projects
async function fetchProjects() {
  projectsLoading.value = true
  try {
    projects.value = await getProjects()
  } catch (error) {
    message.error(t('createTask.failedToFetchProjects'))
  } finally {
    projectsLoading.value = false
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

// Fetch branches when project changes
async function fetchBranches(projectId: number) {
  branchesLoading.value = true
  branches.value = []
  try {
    branches.value = await getBranches(projectId)
    // Reset branch selection
    formValue.value.branch_name = ''
  } catch (error) {
    message.error(t('createTask.failedToFetchBranches'))
  } finally {
    branchesLoading.value = false
  }
}

function handleProjectChange(projectId: number) {
  if (projectId) {
    fetchBranches(projectId)
    formValue.value.base_branch = undefined
    formValue.value.new_branch_name = ''
    // Set target_branch to the project's default branch only when MR creation is enabled
    if (createMR.value) {
      const project = projects.value.find(p => p.id === projectId)
      formValue.value.target_branch = project?.default_branch || 'main'
    }
  }
}

function handleBaseBranchChange(_branch: string) {
  // Reset new branch name when base branch changes
  formValue.value.new_branch_name = ''
}

function handleCreateMRChange(value: boolean) {
  if (value && formValue.value.project_id) {
    // Restore project default branch when toggling MR creation back on
    const project = projects.value.find(p => p.id === formValue.value.project_id)
    formValue.value.target_branch = project?.default_branch || 'main'
  }
}

async function handleReset() {
  branches.value = []
  Object.assign(formValue.value, createInitialFormValue())
  scheduleType.value = 'now'
  delayValue.value = 5
  delayUnit.value = 'minutes'
  scheduledDatetime.value = null
  createMR.value = true
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
    // Determine branch_name: use new_branch_name if provided, otherwise auto-generate
    const branchName = formValue.value.new_branch_name?.trim() || `ai-task-${Date.now()}`

    // Prepare request; base_branch is the branch to fork from (sent separately)
    const request: CreateTaskRequest = {
      project_id: formValue.value.project_id,
      branch_name: branchName,
      base_branch: formValue.value.base_branch || undefined,
      target_branch: createMR.value ? formValue.value.target_branch : null,
      user_prompt: formValue.value.user_prompt,
      priority: formValue.value.priority
    }

    Object.assign(request, buildScheduleRequest())

    const task = await createTask(request)
    createdTaskId.value = task.id
    showSuccessModal.value = true
  } catch (error) {
    const errorMessage = error instanceof Error ? error.message : t('createTask.failedToCreateTask')
    message.error(errorMessage)
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
  void handleReset()
}

onMounted(() => {
  fetchProjects()
  fetchPromptTemplates()
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

.create-task-form__warning {
  margin-top: 6px;
  font-size: 12px;
  color: #d03050;
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

.create-task-form__toggle-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  cursor: default;
}

.create-task-form__toggle-label-icon {
  opacity: 0.55;
  vertical-align: middle;
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

.priority-btn__dot {
  display: inline-block;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  margin-right: 6px;
  vertical-align: middle;
  margin-top: -1px;
}

.priority-btn--p0 .priority-btn__dot {
  background-color: #d03050;
}

.priority-btn--p1 .priority-btn__dot {
  background-color: #f0a020;
}

.priority-btn--p2 .priority-btn__dot {
  background-color: #18a058;
}
</style>
