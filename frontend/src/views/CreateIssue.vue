<template>
  <div class="create-issue-page" data-testid="create-issue-page">
    <n-space vertical :size="16">
      <PageHeader
        data-testid="create-issue-header"
        root-class="create-issue-page__hero"
        title-class="create-issue-page__title"
        subtitle-class="create-issue-page__subtitle"
        :title="t('issue.create')"
        :subtitle="t('issue.subtitle')"
      >
        <template #actions>
          <n-button secondary round @click="router.back()">
            {{ t('common.cancel') }}
          </n-button>
        </template>
      </PageHeader>

      <n-card class="create-issue-card" :bordered="false">
        <n-spin :show="loading">
          <n-form
            ref="formRef"
            :model="formValue"
            :rules="rules"
            label-placement="top"
            class="create-issue-form"
            data-testid="create-issue-form"
          >
            <div class="create-issue-form__section">
              <div class="create-issue-form__section-title">{{ t('issue.field.project') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('issue.field.project')" path="project_id">
                    <n-select
                      v-model:value="formValue.project_id"
                      :options="projectOptions"
                      :loading="projectsLoading"
                      :placeholder="t('createTask.selectProject')"
                      filterable
                      data-testid="create-issue-project"
                      @update:value="handleProjectChange"
                    />
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-issue-form__section">
              <div class="create-issue-form__section-title">{{ t('issue.field.title') }}</div>
              <n-form-item :label="t('issue.field.title')" path="title">
                <n-input
                  v-model:value="formValue.title"
                  :placeholder="t('issue.field.title')"
                  data-testid="create-issue-title"
                />
              </n-form-item>

              <n-form-item :label="t('issue.field.description')" path="description">
                <n-input
                  v-model:value="formValue.description"
                  type="textarea"
                  :rows="6"
                  :placeholder="t('issue.field.description')"
                  data-testid="create-issue-description"
                />
              </n-form-item>
            </div>

            <div class="create-issue-form__section">
              <div class="create-issue-form__section-title">{{ t('issue.field.baseBranch') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('issue.field.baseBranch')" path="base_branch">
                    <n-select
                      v-model:value="formValue.base_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      :disabled="!formValue.project_id"
                      :placeholder="t('createTask.selectBaseBranch')"
                      filterable
                      data-testid="create-issue-base-branch"
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('issue.field.targetBranch')" path="target_branch">
                    <n-select
                      v-model:value="formValue.target_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      :disabled="!formValue.project_id"
                      :placeholder="t('createTask.selectTargetBranch')"
                      filterable
                      data-testid="create-issue-target-branch"
                    />
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>

            <div class="create-issue-form__actions">
              <n-space justify="end" wrap>
                <n-button secondary strong round @click="handleReset">
                  {{ t('common.reset') }}
                </n-button>
                <n-button
                  type="primary"
                  strong
                  round
                  :loading="submitting"
                  :disabled="submitting"
                  data-testid="create-issue-submit"
                  @click="handleSubmit"
                >
                  {{ t('issue.create') }}
                </n-button>
              </n-space>
            </div>
          </n-form>
        </n-spin>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useMessage, type FormInst, type FormRules } from 'naive-ui'
import PageHeader from '../components/PageHeader.vue'
import { createIssue, getProjects, getBranches, type Project, type Branch, type CreateIssueRequest } from '../api'
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

// Data
const projects = ref<Project[]>([])
const branches = ref<Branch[]>([])

// Form
const formRef = ref<FormInst | null>(null)

function createInitialFormValue(): {
  title: string
  description: string
  project_id: number | undefined
  base_branch: string | undefined
  target_branch: string | undefined
} {
  return {
    title: '',
    description: '',
    project_id: undefined,
    base_branch: undefined,
    target_branch: undefined,
  }
}

const formValue = ref(createInitialFormValue())

// Validation rules
const rules: FormRules = {
  project_id: {
    required: true,
    type: 'number',
    message: t('createTask.pleaseSelectProject'),
    trigger: 'change',
  },
  title: {
    required: true,
    message: t('issue.field.title'),
    trigger: 'blur',
  },
}

// Options
const projectOptions = computed(() =>
  projects.value.map(p => ({
    label: p.path_with_namespace,
    value: p.id,
  }))
)

const branchOptions = computed(() =>
  branches.value.map(b => ({
    label: b.name,
    value: b.name,
  }))
)

// Fetch projects
async function fetchProjects() {
  projectsLoading.value = true
  try {
    projects.value = await getProjects()
  } catch {
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
    // Auto-set base_branch to the project's default branch
    const project = projects.value.find(p => p.id === projectId)
    const defaultBranch = project?.default_branch
    if (defaultBranch && branches.value.some(b => b.name === defaultBranch)) {
      formValue.value.base_branch = defaultBranch
    }
  } catch {
    message.error(t('createTask.failedToFetchBranches'))
  } finally {
    branchesLoading.value = false
  }
}

function handleProjectChange(projectId: number) {
  if (projectId) {
    formValue.value.base_branch = undefined
    formValue.value.target_branch = undefined
    fetchBranches(projectId)
  }
}

async function handleReset() {
  branches.value = []
  Object.assign(formValue.value, createInitialFormValue())
  formRef.value?.restoreValidation()
}

async function handleSubmit() {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch {
    return
  }

  submitting.value = true

  try {
    const request: CreateIssueRequest = {
      title: formValue.value.title,
      project_id: formValue.value.project_id!,
      description: formValue.value.description || undefined,
      base_branch: formValue.value.base_branch || undefined,
      target_branch: formValue.value.target_branch || undefined,
    }

    const issue = await createIssue(request)
    message.success(t('issue.create'))
    router.push(`/issues/${issue.id}`)
  } catch (error: any) {
    const msg = error?.message || error?.response?.data?.message || String(error)
    message.error(msg)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchProjects()
})
</script>

<style scoped>
.create-issue-page {
  max-width: var(--app-page-max-width);
}

.create-issue-card {
  border-radius: var(--app-card-radius);
}

.create-issue-form__section + .create-issue-form__section,
.create-issue-form__actions {
  margin-top: 20px;
}

.create-issue-form__section-title {
  font-size: 13px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: rgba(15, 23, 42, 0.55);
  margin-bottom: 12px;
}

.create-issue-form__actions {
  padding-top: 16px;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
}
</style>
