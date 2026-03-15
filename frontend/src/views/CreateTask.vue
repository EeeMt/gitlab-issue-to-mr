<template>
  <div class="create-task-page">
    <n-space vertical :size="20">
      <div class="create-task-page__hero">
        <div>
          <h2 class="create-task-page__title">{{ t('createTask.title') }}</h2>
          <p class="create-task-page__subtitle">
            {{ t('createTask.subtitle') }}
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag size="small" round type="info">{{ t('createTask.manualTrigger') }}</n-tag>
          <n-tag size="small" round>{{ t('createTask.schedulerAware') }}</n-tag>
          <n-tag size="small" round>{{ t('createTask.gitlabBranchWorkflow') }}</n-tag>
        </n-space>
      </div>

      <n-card class="create-task-card" :bordered="false">
        <template #header>
          <div class="create-task-card__header">
            <div>
              <div class="create-task-card__title">{{ t('createTask.taskDetails') }}</div>
              <div class="create-task-card__subtitle">{{ t('createTask.taskDetailsSubtitle') }}</div>
            </div>
          </div>
        </template>
        <n-spin :show="loading">
          <n-form :key="formResetKey" ref="formRef" :model="formValue" :rules="rules" label-placement="top" class="create-task-form">
            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.repositoryBranches') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('createTask.project')" path="project_id">
                    <n-select
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
                      v-model:value="formValue.new_branch_name"
                      :placeholder="t('createTask.newBranchPlaceholder')"
                      :disabled="!formValue.project_id || !formValue.base_branch"
                    />
                    <template #feedback>
                      {{ t('createTask.newBranchHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('createTask.targetBranch')" path="target_branch">
                    <n-select
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
              <n-form-item :label="t('createTask.prompt')" path="user_prompt">
                <n-input
                  v-model:value="formValue.user_prompt"
                  type="textarea"
                  :rows="6"
                  :placeholder="t('createTask.promptPlaceholder')"
                />
              </n-form-item>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">{{ t('createTask.prioritySchedule') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('common.priority')" path="priority">
                    <n-radio-group v-model:value="formValue.priority">
                      <n-space vertical :size="8">
                        <n-radio :value="0">{{ t('createTask.p0') }}</n-radio>
                        <n-radio :value="1">{{ t('createTask.p1') }}</n-radio>
                        <n-radio :value="2">{{ t('createTask.p2') }}</n-radio>
                      </n-space>
                    </n-radio-group>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('createTask.schedule')" path="schedule_type">
                    <n-space vertical :size="10" style="width: 100%">
                      <n-radio-group v-model:value="scheduleType" name="scheduleType">
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
                       />

                      <div class="create-task-form__hint">
                        {{ scheduleSummary }}
                      </div>
                    </n-space>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-task-form__actions">
              <n-space justify="end" wrap>
                <n-button secondary strong round @click="handleReset">
                  {{ t('common.reset') }}
                </n-button>
                <n-button type="primary" strong round @click="handleSubmit" :loading="submitting">
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
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NForm, NFormItem, NSelect, NInput, NInputNumber,
  NButton, NSpin, NSpace, NRadioGroup, NRadio, NModal,
  NDatePicker, NTag, NGrid, NGi, useMessage, FormInst, FormRules
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { useI18n } from 'vue-i18n'
import { getProjects, getBranches, createTask, type Project, type Branch, type CreateTaskRequest } from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { width } = useWindowSize()
const isMobile = computed(() => width.value < 768)

// Loading states
const loading = ref(false)
const projectsLoading = ref(false)
const branchesLoading = ref(false)
const submitting = ref(false)

// Data
const projects = ref<Project[]>([])
const branches = ref<Branch[]>([])

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
  return (formValue.value.new_branch_name || formValue.value.base_branch || '').trim()
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
  }
}

function handleBaseBranchChange(_branch: string) {
  // Reset new branch name when base branch changes
  formValue.value.new_branch_name = ''
}

async function handleReset() {
  branches.value = []
  Object.assign(formValue.value, createInitialFormValue())
  scheduleType.value = 'now'
  delayValue.value = 5
  delayUnit.value = 'minutes'
  scheduledDatetime.value = null
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
    // Determine branch_name: use new_branch_name if provided, otherwise use base_branch
    const branchName = formValue.value.new_branch_name || formValue.value.base_branch || ''

    if (branchName === formValue.value.target_branch) {
      message.error(t('createTask.manualTaskBranchConflict'))
      return
    }

    // Prepare request
    const request: CreateTaskRequest = {
      project_id: formValue.value.project_id,
      branch_name: branchName,
      target_branch: formValue.value.target_branch,
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
})
</script>

<style scoped>
.create-task-page {
  max-width: 1240px;
}

.create-task-page__hero {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
}

.create-task-page__title {
  margin: 0;
  font-size: 28px;
  line-height: 1.2;
}

.create-task-page__subtitle {
  margin: 8px 0 0;
  color: rgba(15, 23, 42, 0.68);
  max-width: 760px;
}

.create-task-card {
  border-radius: 18px;
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
  width: min(100%, calc(19ch + 9.5rem));
}

.create-task-form__warning {
  margin-top: 6px;
  font-size: 12px;
  color: #d03050;
}

@media (max-width: 768px) {
  .create-task-page__hero,
  .create-task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .create-task-form__actions {
    justify-content: stretch;
  }

  .create-task-page__title {
    font-size: 24px;
  }
}
</style>
