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
                />
              </n-form-item>

              <div class="prompt-label-row">
                <span class="prompt-label">{{ t('issue.field.description') }}</span>
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
              <n-form-item path="description" :show-label="false">
                <VariableEditor
                  v-model="formValue.description"
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

            <div class="create-issue-form__section">
              <div class="create-issue-form__section-title">{{ t('issue.field.baseBranch') }}</div>
              <n-grid :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('issue.field.baseBranch')" path="base_branch">
                    <n-select
                      v-model:value="formValue.base_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      :disabled="!formValue.project_id"
                      :placeholder="t('createTask.selectBaseBranch')"
                      filterable
                    />
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('issue.createMergeRequest')" path="create_mr">
                    <n-space align="center" :size="8">
                      <n-switch v-model:value="formValue.create_mr" :disabled="!formValue.project_id" />
                      <span style="font-size: 13px; color: var(--n-text-color-2)">
                        {{ formValue.create_mr ? t('issue.mrEnabled') : t('issue.mrDisabled') }}
                      </span>
                    </n-space>
                  </n-form-item>
                </n-gi>
                <n-gi v-if="formValue.create_mr">
                  <n-form-item :label="t('issue.field.targetBranch')" path="target_branch">
                    <n-select
                      v-model:value="formValue.target_branch"
                      :options="branchOptions"
                      :loading="branchesLoading"
                      :disabled="!formValue.project_id"
                      :placeholder="t('createTask.selectTargetBranch')"
                      filterable
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
import { ref, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NDrawer,
  NDrawerContent,
  NIcon,
  useMessage,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { DocumentTextOutline, WarningOutline } from '@vicons/ionicons5'
import PageHeader from '../components/PageHeader.vue'
import VariableEditor from '../components/VariableEditor.vue'
import { createIssue, getProjects, getBranches, getPromptTemplates, type Project, type Branch, type CreateIssueRequest, type PromptTemplate } from '../api'
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

// Template picker state
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)
const showTemplateDrawer = ref(false)

// Detect unreplaced variables in description
const unreplacedVariables = computed(() => {
  const content = formValue.value.description || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

// Form
const formRef = ref<FormInst | null>(null)

function createInitialFormValue(): {
  title: string
  description: string
  project_id: number | undefined
  base_branch: string | undefined
  target_branch: string | undefined
  create_mr: boolean
} {
  return {
    title: '',
    description: '',
    project_id: undefined,
    base_branch: undefined,
    target_branch: undefined,
    create_mr: false,
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
      // Also set target_branch if create_mr is enabled
      if (formValue.value.create_mr) {
        formValue.value.target_branch = defaultBranch
      }
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

// When MR toggle is switched on, auto-fill target_branch with project default
watch(
  () => formValue.value.create_mr,
  (enabled) => {
    if (enabled && formValue.value.project_id && !formValue.value.target_branch) {
      const project = projects.value.find(p => p.id === formValue.value.project_id)
      const defaultBranch = project?.default_branch
      if (defaultBranch && branches.value.some(b => b.name === defaultBranch)) {
        formValue.value.target_branch = defaultBranch
      }
    }
  }
)

// Fetch prompt templates
async function fetchPromptTemplates() {
  promptTemplatesLoading.value = true
  try {
    promptTemplates.value = await getPromptTemplates()
  } catch {
    // Non-critical
  } finally {
    promptTemplatesLoading.value = false
  }
}

function applyPromptTemplate(tmpl: PromptTemplate) {
  formValue.value.description = tmpl.content
  if (tmpl.variable_tips) {
    promptVariableTips.value = tmpl.variable_tips
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
      target_branch: formValue.value.create_mr ? formValue.value.target_branch || undefined : undefined,
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
  fetchPromptTemplates()
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

.prompt-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}

.prompt-label {
  font-size: 14px;
  font-weight: 500;
}

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #f0a020;
  font-size: 12px;
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

.prompt-template-dropdown__item-name {
  font-weight: 600;
  margin-bottom: 4px;
}

.prompt-template-dropdown__item-preview {
  font-size: 12px;
  color: var(--n-text-color-3);
}
</style>
