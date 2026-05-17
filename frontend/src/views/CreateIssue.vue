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
                <div>
                  <span class="prompt-label">{{ t('issue.field.description') }}</span>
                  <div class="description-hint">
                    {{ t('issue.field.descriptionHint') }}
                  </div>
                </div>
                <n-button
                  size="small"
                  :disabled="promptTemplatesLoading || promptTemplates.length === 0"
                  :loading="promptTemplatesLoading"
                  type="primary"
                  ghost
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
              <div class="create-issue-form__section-title">{{ t('issue.field.branchStrategy') }}</div>

              <!-- Branch Strategy Visual Flow -->
              <div class="branch-flow-viz">
                <div class="branch-flow-viz__node branch-flow-viz__node--base">
                  <n-icon :component="GitBranchOutline" size="14" class="branch-flow-viz__node-icon" />
                  <span class="branch-flow-viz__node-type">{{ t('issue.field.baseBranch') }}</span>
                  <span class="branch-flow-viz__node-name">{{ formValue.base_branch || '—' }}</span>
                </div>

                <div class="branch-flow-viz__connector">
                  <span class="branch-flow-viz__connector-label">{{ t('createTask.branchFlowAiCreates') }}</span>
                  <div class="branch-flow-viz__connector-arrow" />
                </div>

                <div class="branch-flow-viz__node branch-flow-viz__node--work">
                  <n-icon :component="SparklesOutline" size="14" class="branch-flow-viz__node-icon" />
                  <span class="branch-flow-viz__node-type">{{ t('createTask.branchFlowWorkBranch') }}</span>
                  <span class="branch-flow-viz__node-name">codify/issue-{id}</span>
                </div>

                <template v-if="formValue.create_mr">
                  <div class="branch-flow-viz__connector">
                    <span class="branch-flow-viz__connector-label">{{ t('createTask.branchFlowMrMerge') }}</span>
                    <div class="branch-flow-viz__connector-arrow" />
                  </div>
                  <div class="branch-flow-viz__node branch-flow-viz__node--target">
                    <n-icon :component="GitMergeOutline" size="14" class="branch-flow-viz__node-icon" />
                    <span class="branch-flow-viz__node-type">{{ t('issue.field.targetBranch') }}</span>
                    <span class="branch-flow-viz__node-name">{{ formValue.target_branch || '—' }}</span>
                  </div>
                </template>
              </div>

              <!-- Row 1: Starting Branch | Create MR | Merge Target -->
              <n-grid :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="8" style="margin-top: 16px;">
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
                  <div class="field-hint">{{ t('createTask.baseBranchHint') }}</div>
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
                  <div class="field-hint">{{ t('createTask.targetBranchHint') }}</div>
                </n-gi>
              </n-grid>

              <!-- Row 2: Delete working branch on close -->
              <div class="branch-extra-row">
                <n-form-item :label="t('issue.deleteBranchOnClose')" path="delete_branch_on_close">
                  <n-space align="center" :size="8">
                    <n-switch v-model:value="formValue.delete_branch_on_close" />
                    <span style="font-size: 13px; color: var(--n-text-color-2)">
                      {{ formValue.delete_branch_on_close ? t('issue.deleteBranchOnCloseEnabled') : t('issue.deleteBranchOnCloseDisabled') }}
                    </span>
                  </n-space>
                </n-form-item>
              </div>
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
  NIcon,
  useMessage,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { DocumentTextOutline, WarningOutline, CloseOutline, GitBranchOutline, SparklesOutline, GitMergeOutline } from '@vicons/ionicons5'
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
const pendingTemplate = ref<PromptTemplate | null>(null)

watch(showTemplateDrawer, (val) => {
  if (!val) pendingTemplate.value = null
})

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
  delete_branch_on_close: boolean
} {
  return {
    title: '',
    description: '',
    project_id: undefined,
    base_branch: undefined,
    target_branch: undefined,
    create_mr: true,
    delete_branch_on_close: true,
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
  base_branch: {
    required: true,
    message: t('createTask.selectBaseBranch'),
    trigger: 'change',
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

const hasExistingPrompt = computed(() =>
  Boolean(formValue.value.description && formValue.value.description.trim())
)

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

  if (!formValue.value.base_branch) {
    message.error(t('createTask.selectBaseBranch'))
    return
  }

  submitting.value = true

  try {
    const request: CreateIssueRequest = {
      title: formValue.value.title,
      project_id: formValue.value.project_id!,
      description: formValue.value.description || undefined,
      base_branch: formValue.value.base_branch,
      target_branch: formValue.value.create_mr ? formValue.value.target_branch || undefined : undefined,
      delete_branch_on_close: formValue.value.delete_branch_on_close,
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
  margin-bottom: 8px;
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

.field-hint {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
  margin-top: -6px;
  margin-bottom: 4px;
  padding: 0 2px;
  line-height: 1.5;
}

.branch-extra-row {
  margin-top: 4px;
  padding-top: 4px;
}

.description-hint {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
  margin-top: 3px;
  line-height: 1.5;
}

.branch-flow-viz {
  display: flex;
  align-items: center;
  margin-top: 16px;
  padding: 12px 16px;
  background: rgba(15, 23, 42, 0.025);
  border: 1px solid rgba(15, 23, 42, 0.07);
  border-radius: 10px;
  overflow-x: auto;
  gap: 0;
}

.branch-flow-viz__node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 14px;
  border-radius: 8px;
  min-width: 120px;
  text-align: center;
  flex-shrink: 0;
}

.branch-flow-viz__node--base {
  background: rgba(32, 128, 240, 0.07);
  border: 1px solid rgba(32, 128, 240, 0.2);
}

.branch-flow-viz__node--work {
  background: rgba(72, 199, 142, 0.07);
  border: 1px solid rgba(72, 199, 142, 0.25);
}

.branch-flow-viz__node--target {
  background: rgba(240, 160, 32, 0.07);
  border: 1px solid rgba(240, 160, 32, 0.25);
}

.branch-flow-viz__node-icon {
  opacity: 0.55;
}

.branch-flow-viz__node-type {
  font-size: 10px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: rgba(15, 23, 42, 0.45);
}

.branch-flow-viz__node-name {
  font-size: 12px;
  font-weight: 500;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  color: rgba(15, 23, 42, 0.82);
  max-width: 140px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.branch-flow-viz__connector {
  display: flex;
  flex-direction: column;
  align-items: center;
  flex: 1;
  min-width: 72px;
  gap: 5px;
  padding: 0 6px;
}

.branch-flow-viz__connector-label {
  font-size: 10px;
  color: rgba(15, 23, 42, 0.38);
  white-space: nowrap;
}

.branch-flow-viz__connector-arrow {
  width: 100%;
  height: 2px;
  background: rgba(15, 23, 42, 0.15);
  position: relative;
  border-radius: 1px;
}

.branch-flow-viz__connector-arrow::after {
  content: '';
  position: absolute;
  right: -1px;
  top: -4px;
  border-top: 5px solid transparent;
  border-bottom: 5px solid transparent;
  border-left: 7px solid rgba(15, 23, 42, 0.22);
}
</style>
