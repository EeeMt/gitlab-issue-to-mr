<template>
  <div class="create-task-page">
    <n-space vertical :size="20">
      <div class="create-task-page__hero">
        <div>
          <h2 class="create-task-page__title">Create Manual Task</h2>
          <p class="create-task-page__subtitle">
            Start a task directly from the dashboard by choosing the repository, branches, prompt, priority, and schedule.
          </p>
        </div>
        <n-space :size="8" wrap>
          <n-tag size="small" round type="info">Manual trigger</n-tag>
          <n-tag size="small" round>Scheduler aware</n-tag>
          <n-tag size="small" round>GitLab branch workflow</n-tag>
        </n-space>
      </div>

      <n-card class="create-task-card" :bordered="false">
        <template #header>
          <div class="create-task-card__header">
            <div>
              <div class="create-task-card__title">Task Details</div>
              <div class="create-task-card__subtitle">Configure source, branch strategy, priority, and execution timing</div>
            </div>
          </div>
        </template>
        <n-spin :show="loading">
          <n-form ref="formRef" :model="formValue" :rules="rules" label-placement="top" class="create-task-form">
            <div class="create-task-form__section">
              <div class="create-task-form__section-title">Repository & Branches</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Project" path="project_id">
                    <n-select
                      v-model:value="formValue.project_id"
                      :options="projectOptions"
                      :loading="projectsLoading"
                      placeholder="Select a project"
                      @update:value="handleProjectChange"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Base Branch" path="base_branch">
                    <n-select
                      v-model:value="formValue.base_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      placeholder="Select base branch"
                      :disabled="!formValue.project_id"
                      @update:value="handleBaseBranchChange"
                    />
                    <template #feedback>
                      Branch to base changes on.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="New Branch Name" path="new_branch_name">
                    <n-input
                      v-model:value="formValue.new_branch_name"
                      placeholder="Optional: feature/my-task"
                      :disabled="!formValue.project_id || !formValue.base_branch"
                    />
                    <template #feedback>
                      Leave empty to work on the base branch.
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Target Branch" path="target_branch">
                    <n-select
                      v-model:value="formValue.target_branch"
                      :options="targetBranchOptions"
                      :disabled="!formValue.project_id"
                      placeholder="Select target branch"
                    />
                    <template #feedback>
                      Branch to merge changes into.
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">Implementation Prompt</div>
              <n-form-item label="Prompt" path="user_prompt">
                <n-input
                  v-model:value="formValue.user_prompt"
                  type="textarea"
                  :rows="6"
                  placeholder="Describe what you want the AI to implement..."
                />
              </n-form-item>
            </div>

            <div class="create-task-form__section">
              <div class="create-task-form__section-title">Priority & Schedule</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item label="Priority" path="priority">
                    <n-radio-group v-model:value="formValue.priority">
                      <n-space vertical :size="8">
                        <n-radio :value="0">P0 (Highest)</n-radio>
                        <n-radio :value="1">P1 (High)</n-radio>
                        <n-radio :value="2">P2 (Normal)</n-radio>
                      </n-space>
                    </n-radio-group>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item label="Schedule" path="schedule_type">
                    <n-space vertical :size="10" style="width: 100%">
                      <n-radio-group v-model:value="scheduleType" name="scheduleType">
                        <n-space vertical :size="8">
                          <n-radio value="now">Execute Now</n-radio>
                          <n-radio value="delay">Delay</n-radio>
                          <n-radio value="scheduled">Schedule at</n-radio>
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
                            { label: 'seconds', value: 'seconds' },
                            { label: 'minutes', value: 'minutes' },
                            { label: 'hours', value: 'hours' }
                          ]"
                          style="width: 140px"
                        />
                      </n-space>

                      <n-date-picker
                        v-if="scheduleType === 'scheduled'"
                        v-model:value="scheduledDatetime"
                        type="datetime"
                        style="width: min(100%, 320px)"
                        placeholder="Select date and time"
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
              <n-space>
                <n-button type="primary" @click="handleSubmit" :loading="submitting">
                  Create Task
                </n-button>
                <n-button @click="handleReset">
                  Reset
                </n-button>
              </n-space>
            </div>
          </n-form>
        </n-spin>
      </n-card>

      <!-- Success Dialog -->
      <n-modal v-model:show="showSuccessModal" preset="dialog" title="Task Created">
        <n-space vertical>
          <p>Task #{{ createdTaskId }} has been created successfully!</p>
          <n-space>
            <n-button @click="viewTask">View Task</n-button>
            <n-button type="primary" @click="createAnother">Create Another</n-button>
          </n-space>
        </n-space>
      </n-modal>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import {
  NCard, NForm, NFormItem, NSelect, NInput, NInputNumber,
  NButton, NSpin, NSpace, NRadioGroup, NRadio, NModal,
  NDatePicker, NTag, NGrid, NGi, useMessage, FormInst, FormRules
} from 'naive-ui'
import { useWindowSize } from '@vueuse/core'
import { getProjects, getBranches, createTask, type Project, type Branch, type CreateTaskRequest } from '../api'
import { formatDateTimeUtc8 } from '../utils/datetime'

const router = useRouter()
const message = useMessage()
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
const formValue = ref<CreateTaskRequest & { base_branch?: string; new_branch_name?: string; branch_name?: string }>({
  project_id: undefined,
  base_branch: undefined,
  new_branch_name: '',
  branch_name: '',
  target_branch: 'main',
  user_prompt: '',
  priority: 0,
  delay_seconds: undefined,
  scheduled_datetime: undefined
})

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

const scheduleSummary = computed(() => {
  if (scheduleType.value === 'now') {
    return 'This task will execute immediately after creation.'
  }

  if (scheduleType.value === 'delay') {
    if (!delayValue.value || delayValue.value <= 0) {
      return 'Enter a delay greater than 0 before creating the task.'
    }
    return `This task will run after ${delayValue.value} ${delayUnit.value}.`
  }

  if (!scheduledDatetime.value) {
    return 'Select a future date and time before creating the task.'
  }

  return `This task will run at ${formatDateTimeUtc8(scheduledDatetime.value)} (UTC+8).`
})

// Validation rules
const rules: FormRules = {
  project_id: {
    required: true,
    type: 'number',
    message: 'Please select a project',
    trigger: 'change'
  },
  base_branch: {
    required: true,
    message: 'Please select a base branch',
    trigger: 'change'
  },
  target_branch: {
    required: true,
    message: 'Please select target branch',
    trigger: 'change'
  },
  user_prompt: {
    required: true,
    message: 'Please enter a prompt',
    trigger: 'blur'
  }
}

// Fetch projects
async function fetchProjects() {
  projectsLoading.value = true
  try {
    projects.value = await getProjects()
  } catch (error) {
    message.error('Failed to fetch projects')
  } finally {
    projectsLoading.value = false
  }
}

// Fetch branches when project changes
async function fetchBranches(projectId: number) {
  branchesLoading.value = true
  try {
    branches.value = await getBranches(projectId)
    // Reset branch selection
    formValue.value.branch_name = ''
  } catch (error) {
    message.error('Failed to fetch branches')
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

function handleReset() {
  formValue.value = {
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
  scheduleType.value = 'now'
  delayValue.value = 5
  delayUnit.value = 'minutes'
  scheduledDatetime.value = null
}

function buildScheduleRequest(): Pick<CreateTaskRequest, 'delay_seconds' | 'scheduled_datetime'> {
  if (scheduleType.value === 'delay') {
    if (delayValue.value === null || !Number.isFinite(delayValue.value) || delayValue.value <= 0) {
      throw new Error('Please enter a valid delay greater than 0')
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
      throw new Error('Please select a scheduled date and time')
    }

    if (scheduledDatetime.value <= Date.now()) {
      throw new Error('Scheduled time must be in the future')
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
    const errorMessage = error instanceof Error ? error.message : 'Failed to create task'
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
  handleReset()
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

@media (max-width: 768px) {
  .create-task-page__hero,
  .create-task-card__header {
    flex-direction: column;
    align-items: flex-start;
  }

  .create-task-page__title {
    font-size: 24px;
  }
}
</style>
