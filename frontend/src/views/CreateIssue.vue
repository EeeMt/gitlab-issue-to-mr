<template>
  <div
    ref="createIssuePageRef"
    class="create-issue-page"
    data-testid="create-issue-page"
  >
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
              <n-form-item
                path="project_id"
                :show-label="false"
                data-form-path="project_id"
              >
                <!-- Search box -->
                <div class="project-picker">
                  <n-input
                    v-model:value="projectSearch"
                    :placeholder="t('createTask.searchProjects')"
                    clearable
                    class="project-picker__search"
                  >
                    <template #prefix>
                      <n-icon :component="SearchOutline" size="15" style="opacity: 0.45" />
                    </template>
                  </n-input>

                  <!-- Loading skeleton -->
                  <div v-if="projectsLoading" class="project-picker__scroll-wrap">
                    <div class="project-picker__grid">
                      <div v-for="i in 6" :key="i" class="project-card project-card--skeleton" />
                    </div>
                  </div>

                  <!-- Empty state -->
                  <div v-else-if="filteredProjects.length === 0" class="project-picker__empty">
                    {{ t('createTask.noProjectsFound') }}
                  </div>

                  <!-- Cards grid (scrollable) -->
                  <div v-else ref="scrollWrapRef" class="project-picker__scroll-wrap">
                    <div class="project-picker__grid">
                      <div
                        v-for="project in filteredProjects"
                        :key="project.id"
                        class="project-card"
                        :class="{
                          'project-card--selected': formValue.project_id === project.id,
                        }"
                        role="option"
                        tabindex="0"
                        :aria-selected="formValue.project_id === project.id"
                        @click="selectProject(project)"
                        @keydown.enter.prevent="selectProject(project)"
                        @keydown.space.prevent="selectProject(project)"
                      >
                        <div
                          class="project-card__avatar"
                          :style="{ background: getAvatarColor(project.name) }"
                        >{{ (project.name?.[0] ?? '?').toUpperCase() }}</div>

                        <div class="project-card__body">
                          <div class="project-card__top">
                            <span class="project-card__name">{{ project.name }}</span>
                            <div v-if="formValue.project_id === project.id" class="project-card__check-badge">
                              <n-icon :component="CheckmarkOutline" size="11" />
                            </div>
                            <span
                              v-else-if="recentProjectIds.slice(0, MAX_RECENT_SHOWN).includes(project.id)"
                              class="project-card__recent-pill"
                            >{{ t('createTask.recentProjects') }}</span>
                          </div>
                          <div class="project-card__namespace">{{ getNamespace(project) }}</div>
                          <div v-if="project.description" class="project-card__description">
                            {{ project.description }}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              </n-form-item>
            </div>

            <div class="create-issue-form__section">
              <div
                class="create-issue-form__section-title"
                data-testid="issue-content-heading"
              >
                {{ t('issue.contentSection') }}
              </div>
              <n-form-item
                :label="t('issue.field.title')"
                path="title"
                data-form-path="title"
              >
                <n-auto-complete
                  v-model:value="formValue.title"
                  :options="recentTitleOptions"
                  :placeholder="t('issue.field.title')"
                  :get-show="() => true"
                />
              </n-form-item>

              <n-form-item
                :label="t('issue.field.description')"
                path="description"
                class="description-form-item"
              >
                <div class="description-field">
                  <div class="description-toolbar">
                    <div class="description-hint">
                      {{ t('issue.field.descriptionHint') }}
                    </div>
                    <n-button
                      size="small"
                      :disabled="promptTemplatesLoading || activePromptTemplates.length === 0"
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
                  <VariableEditor
                    v-model="formValue.description"
                    :variable-tips="promptVariableTips"
                  />
                </div>
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

              <div class="branch-strategy-panel" data-testid="branch-strategy-panel">
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

                  <div
                    class="branch-flow-viz__connector"
                    :class="{ 'branch-flow-viz__connector--inactive': !formValue.create_mr }"
                  >
                    <span class="branch-flow-viz__connector-label">
                      {{ t('createTask.branchFlowMrMerge') }}
                    </span>
                    <div class="branch-flow-viz__connector-arrow" />
                  </div>
                  <div
                    class="branch-flow-viz__node branch-flow-viz__node--target"
                    :class="{ 'branch-flow-viz__node--inactive': !formValue.create_mr }"
                    data-testid="branch-flow-target"
                  >
                    <n-icon :component="GitMergeOutline" size="14" class="branch-flow-viz__node-icon" />
                    <span class="branch-flow-viz__node-type">{{ t('issue.field.targetBranch') }}</span>
                    <span class="branch-flow-viz__node-name">
                      {{
                        formValue.create_mr
                          ? formValue.target_branch || '—'
                          : t('issue.mrDisabled')
                      }}
                    </span>
                  </div>
                </div>

                <div
                  class="branch-strategy-controls"
                  data-testid="branch-strategy-controls"
                >
                  <div class="branch-strategy-controls__grid">
                    <div
                      class="branch-strategy-controls__cell"
                      data-testid="branch-strategy-control-base"
                    >
                      <n-form-item
                        :label="t('issue.field.baseBranch')"
                        path="base_branch"
                        data-form-path="base_branch"
                      >
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
                    </div>
                    <div
                      class="branch-strategy-controls__cell"
                      data-testid="branch-strategy-control-mr"
                    >
                      <n-form-item :label="t('issue.createMergeRequest')" path="create_mr">
                        <n-space align="center" :size="8">
                          <n-switch v-model:value="formValue.create_mr" :disabled="!formValue.project_id" />
                          <span class="branch-strategy-controls__status">
                            {{ formValue.create_mr ? t('issue.mrEnabled') : t('issue.mrDisabled') }}
                          </span>
                        </n-space>
                      </n-form-item>
                    </div>
                    <div
                      class="branch-strategy-controls__cell"
                      data-testid="branch-strategy-control-target"
                    >
                      <div
                        class="branch-strategy-controls__target"
                        :class="{
                          'branch-strategy-controls__target--inactive': !formValue.create_mr,
                        }"
                      >
                        <n-form-item :label="t('issue.field.targetBranch')" path="target_branch">
                          <n-select
                            v-model:value="formValue.target_branch"
                            :options="branchOptions"
                            :loading="branchesLoading"
                            :disabled="!formValue.project_id || !formValue.create_mr"
                            :placeholder="
                              formValue.create_mr
                                ? t('createTask.selectTargetBranch')
                                : t('issue.mrDisabled')
                            "
                            filterable
                            data-testid="target-branch-select"
                          />
                        </n-form-item>
                        <div class="field-hint">{{ t('createTask.targetBranchHint') }}</div>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>

            <div class="create-issue-form__section">
              <div class="create-issue-form__section-heading">
                <div class="create-issue-form__section-title">
                  {{ t('issue.executionEnvironment') }}
                </div>
                <div class="create-issue-form__section-hint">
                  {{ t('issue.executionEnvironmentHint') }}
                </div>
              </div>

              <div class="execution-environment-panel">
                <n-grid :cols="isMobile ? 1 : 3" :x-gap="16" :y-gap="8">
                  <n-gi>
                    <n-form-item
                      :label="t('createTask.workerProfile')"
                      path="worker_profile_id"
                      data-form-path="worker_profile_id"
                    >
                      <n-select
                        v-model:value="workerProfileId"
                        :options="workerProfileOptions"
                        clearable
                        :placeholder="t('createTask.selectDefaultWorkerProfile')"
                        data-testid="worker-profile-select"
                      />
                    </n-form-item>
                    <div class="field-hint">{{ t('issue.workerDefaultHint') }}</div>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('createTask.defaultProvider')">
                      <n-select
                        v-model:value="defaultProviderId"
                        :options="providerOptions"
                        clearable
                        :placeholder="t('config.providers.systemDefault')"
                      />
                    </n-form-item>
                    <div class="field-hint">{{ t('issue.defaultProviderHint') }}</div>
                  </n-gi>
                  <n-gi>
                    <n-form-item :label="t('issue.defaultHarness')">
                      <n-select
                        v-model:value="harnessKey"
                        :options="harnessOptions"
                        clearable
                        :disabled="!selectedWorkerProfile"
                        :placeholder="t('issue.defaultHarnessPlaceholder')"
                        data-testid="default-harness-select"
                      />
                    </n-form-item>
                    <div class="field-hint">{{ t('issue.defaultHarnessHint') }}</div>
                  </n-gi>
                </n-grid>
              </div>
            </div>

            <div class="create-issue-form__section create-issue-form__section--advanced">
              <details
                ref="advancedSettingsRef"
                class="advanced-settings"
                data-testid="advanced-settings"
              >
                <summary
                  class="advanced-settings__summary"
                  data-testid="advanced-settings-summary"
                >
                  <span class="advanced-settings__summary-copy">
                    <span class="advanced-settings__title">
                      {{ t('issue.advancedSettings') }}
                    </span>
                    <span class="advanced-settings__hint">
                      {{ t('issue.advancedSettingsHint') }}
                    </span>
                  </span>
                  <span class="advanced-settings__summary-meta">
                    <span class="advanced-settings__summary-state">
                      <span class="advanced-settings__summary-state-label">
                        {{ t('issue.repositoryCloneSummaryLabel') }}
                      </span>
                      <span class="advanced-settings__summary-state-value">
                        {{
                          cloneMode === 'shallow'
                            ? t('issue.repositoryCloneShallowBadge', {
                                depth: formValue.git_clone_depth ?? DEFAULT_GIT_CLONE_DEPTH,
                              })
                            : t('issue.repositoryCloneFull')
                        }}
                      </span>
                    </span>
                    <span
                      v-if="formValue.git_clone_filter === 'blob:none'"
                      class="advanced-settings__summary-state"
                    >
                      <span class="advanced-settings__summary-state-label">
                        {{ t('issue.repositoryCloneContentLabel') }}
                      </span>
                      <span class="advanced-settings__summary-state-value">
                        {{ t('issue.repositoryCloneContentOnDemand') }}
                      </span>
                    </span>
                    <span class="advanced-settings__summary-state">
                      <span class="advanced-settings__summary-state-label">
                        {{ t('issue.branchCleanupSummaryLabel') }}
                      </span>
                      <span class="advanced-settings__summary-state-value">
                        {{
                          formValue.delete_branch_on_close
                            ? t('issue.branchCleanupSummaryDelete')
                            : t('issue.branchCleanupSummaryKeep')
                        }}
                      </span>
                    </span>
                    <span class="advanced-settings__summary-state">
                      <span class="advanced-settings__summary-state-label">
                        {{ t('issue.ciAutoRepairSummaryLabel') }}
                      </span>
                      <span class="advanced-settings__summary-state-value">
                        {{
                          selectedProject && ciAutoRepairStatusLoading
                            ? t('issue.settingSummaryChecking')
                            : selectedProject && !ciAutoRepairAvailable
                              ? t('issue.settingSummaryUnavailable')
                              : formValue.ci_auto_repair_enabled
                                ? t('issue.settingSummaryEnabled')
                                : t('issue.settingSummaryDisabled')
                        }}
                      </span>
                    </span>
                  </span>
                  <span class="advanced-settings__chevron" aria-hidden="true" />
                </summary>

                <div class="advanced-settings__body">
                  <div class="repository-clone-options" data-testid="repository-clone-options">
                    <div class="advanced-settings__group-heading">
                      <span class="advanced-settings__group-title">
                        {{ t('issue.repositoryPreparation') }}
                      </span>
                      <span class="advanced-settings__group-hint">
                        {{ t('issue.repositoryPreparationHint') }}
                      </span>
                    </div>
                    <div class="repository-clone-options__controls">
                      <div
                        class="repository-clone-options__field repository-clone-options__field--mode"
                      >
                        <n-form-item :label="t('issue.repositoryCloneMode')">
                          <n-select
                            :value="cloneMode"
                            :options="cloneModeOptions"
                            class="repository-clone-options__mode-select"
                            data-testid="git-clone-mode-select"
                            @update:value="handleCloneModeChange"
                          />
                        </n-form-item>
                        <div class="field-hint repository-clone-options__hint">
                          {{
                            cloneMode === 'shallow'
                              ? t('issue.repositoryCloneShallowHint')
                              : t('issue.repositoryCloneFullHint')
                          }}
                        </div>
                      </div>
                      <div
                        v-if="cloneMode === 'shallow'"
                        class="repository-clone-options__field repository-clone-options__field--depth"
                      >
                        <n-form-item
                          :label="t('issue.repositoryCloneDepth')"
                          path="git_clone_depth"
                          data-form-path="git_clone_depth"
                        >
                          <n-input-number
                            v-model:value="formValue.git_clone_depth"
                            :min="1"
                            :max="10000"
                            :step="10"
                            data-testid="git-clone-depth-input"
                          />
                        </n-form-item>
                      </div>
                      <div
                        class="repository-clone-options__field repository-clone-options__field--filter"
                      >
                        <n-form-item
                          :label="t('issue.repositoryCloneFilter')"
                          path="git_clone_filter"
                          data-form-path="git_clone_filter"
                        >
                          <n-space align="center" :size="8">
                            <n-switch
                              :value="formValue.git_clone_filter === 'blob:none'"
                              :disabled="
                                repositoryCloneSettingsUnavailable
                                && formValue.git_clone_filter === null
                              "
                              data-testid="git-clone-filter-switch"
                              @update:value="handleCloneFilterChange"
                            />
                            <span class="repository-clone-options__status">
                              {{
                                formValue.git_clone_filter === 'blob:none'
                                  ? t('issue.repositoryCloneFilterEnabled')
                                  : t('issue.repositoryCloneFilterDisabled')
                              }}
                            </span>
                          </n-space>
                        </n-form-item>
                      </div>
                    </div>
                    <div
                      v-if="repositoryCloneCompatibilityMessage"
                      class="repository-clone-options__compatibility"
                      data-testid="repository-clone-compatibility"
                    >
                      <n-icon :component="WarningOutline" size="14" />
                      <span>{{ repositoryCloneCompatibilityMessage }}</span>
                    </div>
                  </div>

                  <div class="advanced-settings__automation-grid">
                    <n-form-item
                      path="delete_branch_on_close"
                      :show-label="false"
                      :show-feedback="false"
                      class="advanced-setting-card"
                    >
                      <div class="advanced-setting-card__header">
                        <span class="advanced-setting-card__title">
                          {{ t('issue.deleteBranchOnClose') }}
                        </span>
                        <n-switch
                          v-model:value="formValue.delete_branch_on_close"
                          data-testid="delete-branch-on-close-switch"
                        />
                      </div>
                      <div class="advanced-setting-card__description">
                        {{
                          formValue.delete_branch_on_close
                            ? t('issue.deleteBranchOnCloseEnabled')
                            : t('issue.deleteBranchOnCloseDisabled')
                        }}
                      </div>
                    </n-form-item>

                    <n-form-item
                      path="ci_auto_repair_enabled"
                      :show-label="false"
                      :show-feedback="false"
                      class="advanced-setting-card"
                    >
                      <div class="advanced-setting-card__header">
                        <span class="advanced-setting-card__title">
                          {{ t('issue.ciAutoRepair') }}
                        </span>
                        <n-switch
                          v-model:value="formValue.ci_auto_repair_enabled"
                          :disabled="!formValue.create_mr || !ciAutoRepairAvailable"
                          data-testid="ci-auto-repair-switch"
                        />
                      </div>
                      <div
                        class="advanced-setting-card__description ci-auto-repair-status"
                        :class="{
                          'ci-auto-repair-status--unavailable':
                            selectedProject && !ciAutoRepairStatusLoading && !ciAutoRepairAvailable,
                        }"
                        data-testid="ci-auto-repair-status"
                      >
                        {{ ciAutoRepairStatusText }}
                      </div>
                    </n-form-item>
                  </div>
                </div>
              </details>
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
            <div v-if="activePromptTemplates.length > 0" class="template-tag-filter">
              <n-select
                :value="selectedTemplateTags"
                :show="templateTagFilterVisible"
                multiple
                clearable
                :options="templateTagOptions"
                :placeholder="t('createTask.filterTemplatesByTags')"
                @update:value="handleTemplateTagFilterUpdate"
                @update:show="templateTagFilterVisible = $event"
              />
            </div>
            <div v-if="activePromptTemplates.length === 0" class="prompt-template-dropdown__empty">
              {{ t('createTask.noPromptTemplates') }}
            </div>
            <div v-else-if="filteredPromptTemplates.length === 0" class="prompt-template-dropdown__empty">
              {{ t('createTask.noMatchingPromptTemplates') }}
            </div>
            <div
              v-for="tmpl in filteredPromptTemplates"
              :key="tmpl.id"
              class="prompt-template-dropdown__item"
              :class="{ 'prompt-template-dropdown__item--pending': pendingTemplate?.id === tmpl.id }"
              @click="handleTemplateItemClick(tmpl)"
            >
              <div class="prompt-template-dropdown__item-name">{{ tmpl.name }}</div>
              <div v-if="(tmpl.tags ?? []).length > 0" class="prompt-template-dropdown__tags">
                <n-tag
                  v-for="tag in tmpl.tags ?? []"
                  :key="tag"
                  size="small"
                  round
                >
                  {{ tag }}
                </n-tag>
              </div>
              <div class="prompt-template-dropdown__item-preview">{{ tmpl.content.substring(0, 80) }}...</div>
            </div>
          </div>
        </div>
      </n-drawer>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import {
  NAutoComplete,
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NDrawer,
  NIcon,
  NTag,
  useMessage,
  type FormInst,
  type FormRules,
} from 'naive-ui'
import { DocumentTextOutline, WarningOutline, CloseOutline, GitBranchOutline, SparklesOutline, GitMergeOutline, SearchOutline, CheckmarkOutline } from '@vicons/ionicons5'
import PageHeader from '../components/PageHeader.vue'
import VariableEditor from '../components/VariableEditor.vue'
import {
  createIssue,
  getBranches,
  getProjectCIAutoRepairAvailability,
  getProjects,
  getPromptTemplates,
  getProviders,
  getWorkerProfiles,
  type Branch,
  type CreateIssueRequest,
  type AIProvider,
  type Project,
  type ProjectCIAutoRepairAvailability,
  type PromptTemplate,
  type WorkerProfile,
} from '../api'
import { useBreakpoints } from '../composables/useBreakpoints'
import {
  filterPromptTemplatesByTags,
  getActivePromptTemplates,
  getPromptTemplateTags
} from '../utils/promptTemplates'

const router = useRouter()
const message = useMessage()
const { t } = useI18n()
const { isMobile } = useBreakpoints()

// Loading states
const loading = ref(false)
const projectsLoading = ref(true)   // start true so we show skeleton, not empty state
const branchesLoading = ref(false)
const ciAutoRepairStatusLoading = ref(false)
const submitting = ref(false)
const promptTemplatesLoading = ref(false)

// Data
const projects = ref<Project[]>([])
const branches = ref<Branch[]>([])
const ciAutoRepairAvailability = ref<ProjectCIAutoRepairAvailability | null>(null)
const promptTemplates = ref<PromptTemplate[]>([])
const workerProfiles = ref<WorkerProfile[]>([])
const providers = ref<AIProvider[]>([])
const defaultProviderId = ref<number | null>(null)
const harnessKey = ref<string | null>(null)

// Template picker state
const promptVariableTips = ref<Record<string, string> | undefined>(undefined)
const showTemplateDrawer = ref(false)
const selectedTemplateTags = ref<string[]>([])
const templateTagFilterVisible = ref(false)
const pendingTemplate = ref<PromptTemplate | null>(null)

watch(showTemplateDrawer, (val) => {
  if (!val) pendingTemplate.value = null
})

const activePromptTemplates = computed(() => getActivePromptTemplates(promptTemplates.value))
const templateTagOptions = computed(() =>
  getPromptTemplateTags(activePromptTemplates.value).map(tag => ({ label: tag, value: tag }))
)
const filteredPromptTemplates = computed(() =>
  filterPromptTemplatesByTags(activePromptTemplates.value, selectedTemplateTags.value)
)

// Detect unreplaced variables in description
const unreplacedVariables = computed(() => {
  const content = formValue.value.description || ''
  const matches = content.match(/\{\{([^}]+)\}\}/g)
  if (!matches) return []
  return matches.map(m => m.replace(/\{\{|\}\}/g, ''))
})

// Form
const formRef = ref<FormInst | null>(null)
const createIssuePageRef = ref<HTMLElement | null>(null)
const advancedSettingsRef = ref<HTMLDetailsElement | null>(null)
const formFieldPaths = new Set([
  'project_id',
  'title',
  'base_branch',
  'git_clone_depth',
  'git_clone_filter',
  'worker_profile_id',
])

function findValidationPath(validationErrors: unknown): string | null {
  if (Array.isArray(validationErrors)) {
    for (const error of validationErrors) {
      const path = findValidationPath(error)
      if (path) return path
    }
    return null
  }
  if (
    validationErrors
    && typeof validationErrors === 'object'
    && 'field' in validationErrors
    && typeof validationErrors.field === 'string'
    && formFieldPaths.has(validationErrors.field)
  ) {
    return validationErrors.field
  }
  return null
}

async function scrollToFormField(path: string | null) {
  await nextTick()

  const page = createIssuePageRef.value
  if (!page) return

  let field = path
    ? page.querySelector<HTMLElement>(`[data-form-path="${path}"]`)
    : null
  if (!field) {
    field = page
      .querySelector<HTMLElement>('.n-form-item-blank--error')
      ?.closest<HTMLElement>('[data-form-path]') ?? null
  }
  if (!field) return

  const disclosure = field.closest<HTMLDetailsElement>('details.advanced-settings')
  if (disclosure && !disclosure.open) {
    disclosure.open = true
    await nextTick()
  }

  if (typeof field.scrollIntoView === 'function') {
    const reduceMotion =
      typeof window.matchMedia === 'function'
      && window.matchMedia('(prefers-reduced-motion: reduce)').matches
    field.scrollIntoView({
      behavior: reduceMotion ? 'auto' : 'smooth',
      block: 'center',
    })
  }

  const focusTarget = field.querySelector<HTMLElement>(
    'input:not([type="hidden"]):not([disabled]), '
    + 'textarea:not([disabled]), '
    + 'select:not([disabled]), '
    + '[role="combobox"]:not([aria-disabled="true"]), '
    + 'button:not([disabled]), '
    + '[tabindex]:not([tabindex="-1"])'
  )
  focusTarget?.focus({ preventScroll: true })
}

function createInitialFormValue(): {
  title: string
  description: string
  project_id: number | undefined
  base_branch: string | undefined
  target_branch: string | undefined
  create_mr: boolean
  delete_branch_on_close: boolean
  ci_auto_repair_enabled: boolean
  worker_profile_id: number | null
  git_clone_depth: number | null
  git_clone_filter: 'blob:none' | null
} {
  return {
    title: '',
    description: '',
    project_id: undefined,
    base_branch: undefined,
    target_branch: undefined,
    create_mr: true,
    delete_branch_on_close: true,
    ci_auto_repair_enabled: false,
    worker_profile_id: null,
    git_clone_depth: null,
    git_clone_filter: null,
  }
}

const formValue = ref(createInitialFormValue())
const workerProfileId = computed({
  get: () => formValue.value.worker_profile_id,
  set: value => {
    formValue.value.worker_profile_id = value
  },
})
const DEFAULT_GIT_CLONE_DEPTH = 50
const REPOSITORY_POLICY_MIN_WORKER_KIT_VERSION = [0, 3, 0] as const
const cloneMode = ref<'full' | 'shallow'>('full')

const selectedWorkerProfile = computed(() =>
  workerProfiles.value.find(profile => profile.id === workerProfileId.value) ?? null
)

const harnessOptions = computed(() => {
  const profile = selectedWorkerProfile.value
  const enabled = profile?.enabled_harnesses ?? []
  return enabled.map(key => ({
    label: key === 'codex'
      ? t('createTask.harnessCodex')
      : key === 'claude'
        ? t('createTask.harnessClaude')
        : key === 'pi'
          ? t('createTask.harnessPi')
          : key === 'opencode'
            ? t('createTask.harnessOpenCode')
            : key,
    value: key,
  }))
})

watch(workerProfileId, (id) => {
  const profile = workerProfiles.value.find(p => p.id === id) ?? null
  if (!profile) {
    harnessKey.value = null
    return
  }
  const enabled = profile.enabled_harnesses ?? []
  harnessKey.value = profile.default_harness_key ?? enabled[0] ?? 'claude'
})

function supportsRepositoryCloneSettings(profile: WorkerProfile): boolean {
  if (profile.runtime_mode !== 'mounted_kit') return false

  const rawVersion = profile.worker_kit_version
  if (typeof rawVersion !== 'string') return false
  const release = rawVersion.trim().split('+', 1)[0]
  if (release.includes('-')) return false
  const parts = release.split('.')
  if (parts.length !== 3 || parts.some(part => !/^\d+$/.test(part))) return false

  const version = parts.map(Number)
  for (let index = 0; index < REPOSITORY_POLICY_MIN_WORKER_KIT_VERSION.length; index += 1) {
    if (version[index] > REPOSITORY_POLICY_MIN_WORKER_KIT_VERSION[index]) return true
    if (version[index] < REPOSITORY_POLICY_MIN_WORKER_KIT_VERSION[index]) return false
  }
  return true
}

const repositoryCloneCompatibilityIssue = computed<
  'requires_mounted_kit' | 'requires_worker_kit_version' | null
>(() => {
  const profile = selectedWorkerProfile.value
  if (!profile) return null
  if (profile.runtime_mode !== 'mounted_kit') return 'requires_mounted_kit'
  if (!supportsRepositoryCloneSettings(profile)) return 'requires_worker_kit_version'
  return null
})

const repositoryCloneSettingsUnavailable = computed(
  () => repositoryCloneCompatibilityIssue.value !== null
)

const repositoryCloneCompatibilityMessage = computed(() => {
  if (repositoryCloneCompatibilityIssue.value === 'requires_mounted_kit') {
    return t('issue.repositoryCloneRequiresMountedKit')
  }
  if (repositoryCloneCompatibilityIssue.value === 'requires_worker_kit_version') {
    return t('issue.repositoryCloneRequiresWorkerKitVersion')
  }
  return ''
})

function repositoryCloneCompatibilityError(): Error | null {
  return repositoryCloneCompatibilityMessage.value
    ? new Error(repositoryCloneCompatibilityMessage.value)
    : null
}

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
  worker_profile_id: {
    required: true,
    type: 'number',
    message: t('createTask.selectWorkerProfile'),
    trigger: 'change',
  },
  git_clone_depth: {
    validator: (_rule, value) => {
      if (cloneMode.value === 'shallow') {
        const compatibilityError = repositoryCloneCompatibilityError()
        if (compatibilityError) return compatibilityError
      }
      if (
        (cloneMode.value === 'full' && value === null)
        || (
          cloneMode.value === 'shallow'
          && Number.isInteger(value)
          && value >= 1
          && value <= 10000
        )
      ) {
        return true
      }
      return new Error(t('issue.repositoryCloneDepthInvalid'))
    },
    trigger: 'change',
  },
  git_clone_filter: {
    validator: (_rule, value) => {
      if (value === null) return true
      return repositoryCloneCompatibilityError() ?? true
    },
    trigger: 'change',
  },
}

const branchOptions = computed(() =>
  branches.value.map(b => ({
    label: b.name,
    value: b.name,
  }))
)

const workerProfileOptions = computed(() =>
  workerProfiles.value.map(profile => ({
    label: profile.name,
    value: profile.id,
  }))
)

const providerOptions = computed(() =>
  providers.value.map(provider => ({
    label: `${provider.name} (${provider.model})${provider.is_default ? ' ★' : ''}`,
    value: provider.id,
  }))
)

const cloneModeOptions = computed(() => [
  { label: t('issue.repositoryCloneFull'), value: 'full' },
  {
    label: t('issue.repositoryCloneShallow'),
    value: 'shallow',
    disabled: repositoryCloneSettingsUnavailable.value,
  },
])

function handleCloneModeChange(mode: 'full' | 'shallow') {
  if (mode === 'shallow' && repositoryCloneSettingsUnavailable.value) return
  cloneMode.value = mode
  formValue.value.git_clone_depth =
    mode === 'shallow'
      ? formValue.value.git_clone_depth ?? DEFAULT_GIT_CLONE_DEPTH
      : null
}

function handleCloneFilterChange(enabled: boolean) {
  if (enabled && repositoryCloneSettingsUnavailable.value) return
  formValue.value.git_clone_filter = enabled ? 'blob:none' : null
}

const selectedProject = computed(() =>
  projects.value.find(project => project.id === formValue.value.project_id) ?? null
)

const ciAutoRepairAvailable = computed(
  () =>
    ciAutoRepairAvailability.value?.project_id === formValue.value.project_id
    && ciAutoRepairAvailability.value?.ci_auto_repair_available === true
)

const ciAutoRepairUnavailableReason = computed(() => {
  const issues = ciAutoRepairAvailability.value?.webhook_status_issues
  const issueCodes = issues?.length ? issues : ['webhook_status_unavailable']
  return issueCodes
    .map(issue => t(`issue.ciAutoRepairWebhookIssues.${issue}`))
    .join(t('issue.ciAutoRepairReasonSeparator'))
})

const ciAutoRepairStatusText = computed(() => {
  if (selectedProject.value && ciAutoRepairStatusLoading.value) {
    return t('issue.ciAutoRepairCheckingWebhook')
  }
  if (selectedProject.value && !ciAutoRepairAvailable.value) {
    return t('issue.ciAutoRepairUnavailable', {
      reason: ciAutoRepairUnavailableReason.value,
    })
  }
  return formValue.value.ci_auto_repair_enabled
    ? t('issue.ciAutoRepairEnabled')
    : t('issue.ciAutoRepairDisabled')
})

// Project card picker state
const RECENT_PROJECTS_KEY = 'codify:recent_projects'
const RECENT_TITLES_KEY   = 'codify:recent_titles'
const MAX_RECENT_TITLES   = 10

const projectSearch = ref('')
const scrollWrapRef = ref<HTMLElement | null>(null)

function loadRecentIds(): number[] {
  try { return JSON.parse(localStorage.getItem(RECENT_PROJECTS_KEY) ?? '[]') as number[] }
  catch { return [] }
}
const recentProjectIds = ref<number[]>(loadRecentIds())

function loadRecentTitles(): string[] {
  try { return JSON.parse(localStorage.getItem(RECENT_TITLES_KEY) ?? '[]') as string[] }
  catch { return [] }
}
const recentTitles = ref<string[]>(loadRecentTitles())

const recentTitleOptions = computed(() => {
  const q = formValue.value.title.trim().toLowerCase()
  const list = q
    ? recentTitles.value.filter(t => t.toLowerCase().includes(q))
    : recentTitles.value
  return list.map(t => ({ label: t, value: t }))
})

const MAX_RECENT_STORED = 5
const MAX_RECENT_SHOWN  = 3

function getNamespace(project: Project): string {
  const ns = project.path_with_namespace
  const suffix = '/' + project.name
  return ns.endsWith(suffix) ? ns.slice(0, -suffix.length) : ns
}

const AVATAR_COLORS = [
  '#3b82f6', '#8b5cf6', '#ec4899', '#f59e0b',
  '#10b981', '#06b6d4', '#f97316', '#6366f1',
  '#14b8a6', '#84cc16',
]
function getAvatarColor(name: string): string {
  const hash = [...name].reduce((h, c) => (h * 31 + c.charCodeAt(0)) & 0xffff, 0)
  return AVATAR_COLORS[hash % AVATAR_COLORS.length]
}

const sortedProjects = computed(() => {
  const recentIds = recentProjectIds.value
  return [...projects.value].sort((a, b) => {
    const ai = recentIds.indexOf(a.id)
    const bi = recentIds.indexOf(b.id)
    if (ai !== -1 && bi !== -1) return ai - bi
    if (ai !== -1) return -1
    if (bi !== -1) return 1
    return a.path_with_namespace.localeCompare(b.path_with_namespace)
  })
})

const filteredProjects = computed(() => {
  const q = projectSearch.value.trim().toLowerCase()
  if (!q) return sortedProjects.value
  return sortedProjects.value.filter(
    p =>
      p.name.toLowerCase().includes(q) ||
      p.path_with_namespace.toLowerCase().includes(q) ||
      (p.description || '').toLowerCase().includes(q)
  )
})

// use a template ref to avoid fragile global DOM query
watch(projectSearch, () => {
  scrollWrapRef.value && (scrollWrapRef.value.scrollTop = 0)
})

function saveRecentProject(projectId: number) {
  try {
    const updated = [projectId, ...recentProjectIds.value.filter(id => id !== projectId)].slice(0, MAX_RECENT_STORED)
    recentProjectIds.value = updated    // triggers reactivity
    localStorage.setItem(RECENT_PROJECTS_KEY, JSON.stringify(updated))
  } catch {
    // ignore quota / private-mode errors
  }
}

function saveRecentTitle(title: string) {
  if (!title.trim()) return
  try {
    const updated = [title, ...recentTitles.value.filter(t => t !== title)].slice(0, MAX_RECENT_TITLES)
    recentTitles.value = updated
    localStorage.setItem(RECENT_TITLES_KEY, JSON.stringify(updated))
  } catch {
    // ignore quota / private-mode errors
  }
}

function selectProject(project: Project) {
  formValue.value.project_id = project.id
  handleProjectChange(project.id)
}

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

let ciAutoRepairStatusRequestId = 0

async function fetchCIAutoRepairAvailability(projectId: number) {
  const requestId = ++ciAutoRepairStatusRequestId
  ciAutoRepairStatusLoading.value = true
  ciAutoRepairAvailability.value = null
  formValue.value.ci_auto_repair_enabled = false

  try {
    const availability = await getProjectCIAutoRepairAvailability(projectId)
    if (
      requestId === ciAutoRepairStatusRequestId
      && formValue.value.project_id === projectId
    ) {
      ciAutoRepairAvailability.value = availability
    }
  } catch {
    if (
      requestId === ciAutoRepairStatusRequestId
      && formValue.value.project_id === projectId
    ) {
      ciAutoRepairAvailability.value = {
        project_id: projectId,
        webhook_status: 'error',
        webhook_status_issues: ['webhook_status_unavailable'],
        ci_auto_repair_available: false,
      }
    }
  } finally {
    if (requestId === ciAutoRepairStatusRequestId) {
      ciAutoRepairStatusLoading.value = false
    }
  }
}

function handleProjectChange(projectId: number) {
  if (projectId) {
    formValue.value.base_branch = undefined
    formValue.value.target_branch = undefined
    fetchBranches(projectId)
    fetchCIAutoRepairAvailability(projectId)
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
    if (!enabled) {
      formValue.value.ci_auto_repair_enabled = false
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

async function loadExecutionDefaults() {
  const [workerResult, providerResult] = await Promise.allSettled([
    getWorkerProfiles(),
    getProviders(),
  ])
  if (workerResult.status === 'fulfilled') {
    workerProfiles.value = Array.isArray(workerResult.value)
      ? workerResult.value.filter(profile => profile.enabled)
      : []
  }
  if (providerResult.status === 'fulfilled') {
    providers.value = Array.isArray(providerResult.value)
      ? providerResult.value.filter(provider => !provider.is_disabled)
      : []
    defaultProviderId.value =
      providers.value.find(provider => provider.is_default)?.id ?? null
  }
}

function applyPromptTemplate(tmpl: PromptTemplate) {
  formValue.value.description = tmpl.content
  if (tmpl.variable_tips) {
    promptVariableTips.value = tmpl.variable_tips
  }
}

function handleTemplateTagFilterUpdate(tags: string[] | null) {
  selectedTemplateTags.value = tags ?? []
  templateTagFilterVisible.value = false
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
  ciAutoRepairStatusRequestId += 1
  ciAutoRepairStatusLoading.value = false
  ciAutoRepairAvailability.value = null
  branches.value = []
  projectSearch.value = ''
  Object.assign(formValue.value, createInitialFormValue())
  cloneMode.value = 'full'
  workerProfileId.value = null
  harnessKey.value = null
  defaultProviderId.value =
    providers.value.find(provider => provider.is_default)?.id ?? null
  if (advancedSettingsRef.value) {
    advancedSettingsRef.value.open = false
  }
  formRef.value?.restoreValidation()
}

function localizedRepositoryCloneError(detail: unknown): string | null {
  let code: unknown
  let fallbackMessage: unknown
  if (detail && typeof detail === 'object') {
    code = 'code' in detail ? detail.code : undefined
    fallbackMessage = 'message' in detail ? detail.message : undefined
  }

  if (code === 'repository_clone_requires_mounted_kit') {
    return t('issue.repositoryCloneRequiresMountedKit')
  }
  if (code === 'repository_clone_worker_kit_version_required') {
    return t('issue.repositoryCloneRequiresWorkerKitVersion')
  }

  const legacyMessage =
    typeof detail === 'string'
      ? detail
      : typeof fallbackMessage === 'string'
        ? fallbackMessage
        : ''
  if (legacyMessage.includes('require worker-kit 0.3.0 or newer')) {
    return t('issue.repositoryCloneRequiresWorkerKitVersion')
  }
  if (legacyMessage.includes('require a mounted-kit worker profile')) {
    return t('issue.repositoryCloneRequiresMountedKit')
  }
  return null
}

async function handleSubmit() {
  if (!formRef.value) return

  try {
    await formRef.value.validate()
  } catch (validationErrors) {
    await scrollToFormField(findValidationPath(validationErrors))
    return
  }

  if (!formValue.value.base_branch) {
    await scrollToFormField('base_branch')
    message.error(t('createTask.selectBaseBranch'))
    return
  }
  if (workerProfileId.value === null) {
    await scrollToFormField('worker_profile_id')
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
      ci_auto_repair_enabled:
        formValue.value.create_mr && ciAutoRepairAvailable.value
          ? formValue.value.ci_auto_repair_enabled
          : false,
      worker_profile_id: workerProfileId.value,
      default_provider_id: defaultProviderId.value,
      default_harness_key: harnessKey.value,
      git_clone_depth: formValue.value.git_clone_depth,
      git_clone_filter: formValue.value.git_clone_filter,
    }

    const issue = await createIssue(request)
    saveRecentProject(formValue.value.project_id!)
    saveRecentTitle(formValue.value.title)
    message.success(t('issue.create'))
    router.push(`/issues/${issue.id}`)
  } catch (error: any) {
    const detail = error?.response?.data?.detail
    const detailMessage =
      typeof detail === 'string'
        ? detail
        : detail
          && typeof detail === 'object'
          && 'message' in detail
          && typeof detail.message === 'string'
          ? detail.message
          : error?.response?.data?.message
    const msg =
      localizedRepositoryCloneError(detail)
      || detailMessage
      || error?.message
      || String(error)
    message.error(msg)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchProjects()
  fetchPromptTemplates()
  loadExecutionDefaults()
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

.create-issue-form__section-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
}

.create-issue-form__section-heading .create-issue-form__section-title {
  flex: 0 0 auto;
  margin-bottom: 0;
}

.create-issue-form__section-hint {
  min-width: 0;
  color: rgba(15, 23, 42, 0.42);
  font-size: 12px;
  line-height: 1.5;
}

.create-issue-form__section + .create-issue-form__section--advanced {
  margin-top: 14px;
}

.create-issue-form__actions {
  padding-top: 16px;
  border-top: 1px solid rgba(15, 23, 42, 0.06);
}

.description-field {
  width: 100%;
}

.description-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.description-toolbar :deep(.n-button) {
  flex: 0 0 auto;
}

.prompt-variable-warning {
  display: flex;
  align-items: center;
  gap: 4px;
  color: #f0a020;
  font-size: 12px;
}

.ci-auto-repair-status {
  font-size: 13px;
  color: var(--n-text-color-2);
}

.ci-auto-repair-status--unavailable {
  color: var(--n-text-color-3);
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

.template-tag-filter {
  padding: 8px 16px 12px;
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

.prompt-template-dropdown__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-bottom: 6px;
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

.execution-environment-panel {
  padding: 12px 14px 4px;
  border: 1px solid rgba(15, 23, 42, 0.07);
  border-radius: 10px;
  background: rgba(248, 250, 252, 0.65);
}

.advanced-settings {
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 11px;
  background: rgba(248, 250, 252, 0.45);
}

.advanced-settings__summary {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  min-height: 56px;
  padding: 10px 14px;
  cursor: pointer;
  list-style: none;
  user-select: none;
  transition: background-color 0.16s ease;
}

.advanced-settings__summary::-webkit-details-marker {
  display: none;
}

.advanced-settings__summary::marker {
  content: '';
}

.advanced-settings__summary:hover {
  background: rgba(15, 23, 42, 0.025);
}

.advanced-settings__summary:focus-visible {
  outline: 2px solid rgba(32, 128, 240, 0.55);
  outline-offset: -2px;
}

.advanced-settings__summary-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.advanced-settings__title {
  color: rgba(15, 23, 42, 0.82);
  font-size: 13px;
  font-weight: 600;
  line-height: 1.45;
}

.advanced-settings__hint {
  overflow: hidden;
  color: rgba(15, 23, 42, 0.42);
  font-size: 12px;
  line-height: 1.45;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.advanced-settings__summary-meta {
  display: flex;
  flex: 0 0 auto;
  max-width: 72%;
  margin-left: auto;
  align-items: center;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 6px;
}

.advanced-settings__summary-state {
  display: inline-flex;
  max-width: 230px;
  align-items: center;
  gap: 5px;
  overflow: hidden;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.055);
  font-size: 11px;
  line-height: 1.35;
  white-space: nowrap;
}

.advanced-settings__summary-state-label {
  flex: 0 0 auto;
  color: rgba(15, 23, 42, 0.42);
}

.advanced-settings__summary-state-value {
  min-width: 0;
  overflow: hidden;
  color: rgba(15, 23, 42, 0.68);
  font-weight: 600;
  text-overflow: ellipsis;
}

.advanced-settings__chevron {
  width: 7px;
  height: 7px;
  margin: -3px 3px 0 5px;
  border-right: 1.5px solid rgba(15, 23, 42, 0.45);
  border-bottom: 1.5px solid rgba(15, 23, 42, 0.45);
  transform: rotate(45deg);
  transition: transform 0.16s ease;
}

.advanced-settings[open] .advanced-settings__chevron {
  margin-top: 3px;
  transform: rotate(225deg);
}

.advanced-settings__body {
  padding: 14px;
  border-top: 1px solid rgba(15, 23, 42, 0.07);
  background: rgba(255, 255, 255, 0.72);
}

.advanced-settings__group-heading {
  display: flex;
  align-items: baseline;
  gap: 10px;
  margin-bottom: 12px;
}

.advanced-settings__group-title {
  flex: 0 0 auto;
  color: rgba(15, 23, 42, 0.76);
  font-size: 13px;
  font-weight: 600;
}

.advanced-settings__group-hint {
  color: rgba(15, 23, 42, 0.42);
  font-size: 12px;
  line-height: 1.45;
}

.repository-clone-options {
  margin-bottom: 14px;
  padding-bottom: 14px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.07);
}

.repository-clone-options__controls {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 12px 16px;
}

.repository-clone-options__field {
  min-width: 0;
}

.repository-clone-options__field--mode {
  flex: 0 1 240px;
}

.repository-clone-options__field--depth {
  flex: 0 0 150px;
}

.repository-clone-options__field--filter {
  flex: 1 1 280px;
}

.repository-clone-options__field :deep(.n-form-item) {
  margin-bottom: 0;
}

.repository-clone-options__mode-select,
.repository-clone-options__field--depth :deep(.n-input-number) {
  width: 100%;
}

.repository-clone-options__hint {
  margin: 4px 0 0;
}

.repository-clone-options__status {
  color: var(--n-text-color-2);
  font-size: 13px;
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.repository-clone-options__compatibility {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin-top: 10px;
  padding-top: 10px;
  border-top: 1px solid rgba(240, 160, 32, 0.2);
  color: #d97706;
  font-size: 12px;
  line-height: 1.5;
}

.repository-clone-options__compatibility :deep(.n-icon) {
  flex: 0 0 auto;
  margin-top: 2px;
}

.advanced-settings__automation-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.advanced-setting-card {
  min-width: 0;
  margin-bottom: 0;
  padding: 12px;
  border: 1px solid rgba(15, 23, 42, 0.07);
  border-radius: 9px;
  background: rgba(248, 250, 252, 0.72);
}

.advanced-setting-card :deep(.n-form-item-blank) {
  display: block;
}

.advanced-setting-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.advanced-setting-card__title {
  min-width: 0;
  color: rgba(15, 23, 42, 0.76);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.4;
}

.advanced-setting-card__description {
  margin-top: 6px;
  color: rgba(15, 23, 42, 0.45);
  font-size: 12px;
  line-height: 1.5;
  overflow-wrap: anywhere;
}

@media (max-width: 640px) {
  .create-issue-form__section-heading,
  .advanced-settings__group-heading {
    align-items: flex-start;
    flex-direction: column;
    gap: 3px;
  }

  .advanced-settings__summary {
    position: relative;
    display: block;
    padding: 11px 36px 11px 12px;
  }

  .advanced-settings__hint {
    white-space: normal;
  }

  .advanced-settings__summary-meta {
    max-width: none;
    justify-content: flex-end;
    margin-top: 8px;
    padding-top: 0;
  }

  .advanced-settings__chevron,
  .advanced-settings[open] .advanced-settings__chevron {
    position: absolute;
    top: 23px;
    right: 15px;
    margin: 0;
  }

  .advanced-settings__body {
    padding: 12px;
  }

  .repository-clone-options__controls {
    flex-direction: column;
  }

  .repository-clone-options__field--mode,
  .repository-clone-options__field--depth,
  .repository-clone-options__field--filter {
    flex-basis: auto;
    width: 100%;
  }

  .advanced-settings__automation-grid {
    grid-template-columns: 1fr;
  }

}

.description-hint {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 4px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.45);
  line-height: 1.5;
}

.branch-strategy-panel {
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 11px;
  background: rgba(248, 250, 252, 0.6);
}

.branch-strategy-controls {
  border-top: 1px solid rgba(15, 23, 42, 0.07);
  background: rgba(255, 255, 255, 0.82);
}

.branch-strategy-controls__grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.branch-strategy-controls__cell {
  min-width: 0;
  padding: 12px 14px 4px;
}

.branch-strategy-controls__cell + .branch-strategy-controls__cell {
  border-left: 1px solid rgba(15, 23, 42, 0.065);
}

.branch-strategy-controls__status {
  color: var(--n-text-color-2);
  font-size: 13px;
}

.branch-strategy-controls__target,
.branch-flow-viz__node,
.branch-flow-viz__connector {
  transition: opacity 0.16s ease;
}

.branch-strategy-controls__target--inactive,
.branch-flow-viz__node--inactive,
.branch-flow-viz__connector--inactive {
  opacity: 0.45;
}

.branch-flow-viz {
  display: flex;
  align-items: center;
  min-height: 84px;
  padding: 10px 14px;
  overflow-x: auto;
  background: rgba(15, 23, 42, 0.025);
  gap: 0;
}

.branch-flow-viz__node {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 7px 12px;
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

@media (max-width: 767px) {
  .branch-strategy-controls__grid {
    grid-template-columns: 1fr;
  }

  .branch-strategy-controls__cell {
    padding-right: 12px;
    padding-left: 12px;
  }

  .branch-strategy-controls__cell + .branch-strategy-controls__cell {
    border-top: 1px solid rgba(15, 23, 42, 0.065);
    border-left: 0;
  }
}

/* ── Project picker ──────────────────────────────────── */
.project-picker {
  width: 100%;
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 12px;
  background: rgba(15, 23, 42, 0.02);
  border: 1px solid rgba(15, 23, 42, 0.06);
  border-radius: 12px;
}

.project-picker__search {
  width: 100%;
}

.project-picker__empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 6px;
  padding: 36px 0;
  color: rgba(15, 23, 42, 0.38);
  font-size: 13px;
}

.project-picker__scroll-wrap {
  max-height: 290px;
  overflow-y: auto;
  overflow-x: hidden;
  border-radius: 8px;
  /* padding gives cards room to lift on hover without being clipped
     by the overflow container; compensate margin so visual gap stays same */
  padding: 3px 0;
  margin-top: -3px;
  margin-right: -12px;
}

.project-picker__grid {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  padding-right: 12px; /* compensate for scroll-wrap's -12px margin */
}

@media (max-width: 900px) {
  .project-picker__grid { grid-template-columns: repeat(2, 1fr); }
}
@media (max-width: 560px) {
  .project-picker__grid { grid-template-columns: 1fr; }
}

/* ── Project card ───────────────────────────────────── */
.project-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 11px;
  padding: 12px 13px;
  border: 1.5px solid rgba(15, 23, 42, 0.09);
  border-radius: 12px;
  cursor: pointer;
  background: #fff;
  transition: transform 0.18s cubic-bezier(0.34, 1.4, 0.64, 1),
              box-shadow 0.18s ease,
              border-color 0.18s ease;
  min-height: 68px;
  overflow: hidden;
}

@media (hover: hover) and (pointer: fine) {
  .project-card:hover {
    transform: translateY(-2px);
    border-color: rgba(32, 128, 240, 0.35);
    box-shadow: 0 6px 20px rgba(32, 128, 240, 0.1);
  }
}

.project-card--selected {
  border-color: #2080f0;
  background: linear-gradient(135deg, rgba(32, 128, 240, 0.04) 0%, rgba(32, 128, 240, 0.02) 100%);
  box-shadow: 0 0 0 3px rgba(32, 128, 240, 0.12), 0 4px 16px rgba(32, 128, 240, 0.1);
}

@media (hover: hover) and (pointer: fine) {
  .project-card--selected:hover {
    transform: translateY(-2px);
    box-shadow: 0 0 0 3px rgba(32, 128, 240, 0.18), 0 8px 24px rgba(32, 128, 240, 0.14);
  }
}

/* Skeleton */
.project-card--skeleton {
  background: rgba(15, 23, 42, 0.03);
  border-color: rgba(15, 23, 42, 0.05);
  cursor: default;
  overflow: hidden;
  min-height: 74px;
}

.project-card--skeleton::after {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(
    90deg,
    transparent 0%,
    rgba(255, 255, 255, 0.7) 50%,
    transparent 100%
  );
  background-size: 200% 100%;
  animation: shimmer 1.6s ease-in-out infinite;
}

@keyframes shimmer {
  0%   { background-position: -200% 0; }
  100% { background-position: 200% 0; }
}

/* Avatar */
.project-card__avatar {
  flex-shrink: 0;
  width: 34px;
  height: 34px;
  border-radius: 9px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.02em;
  margin-top: 1px;
  user-select: none;
}

/* Card body */
.project-card__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.project-card__top {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}

.project-card__name {
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.9);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  flex: 1;
  min-width: 0;
  line-height: 1.4;
}

.project-card__check-badge {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  border-radius: 50%;
  background: #2080f0;
  color: #fff;
  display: flex;
  align-items: center;
  justify-content: center;
}

.project-card__recent-pill {
  flex-shrink: 0;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 20px;
  background: rgba(32, 128, 240, 0.1);
  color: #2080f0;
  letter-spacing: 0.01em;
  line-height: 1.6;
  white-space: nowrap;
}

.project-card__namespace {
  font-size: 11px;
  color: rgba(15, 23, 42, 0.4);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  line-height: 1.5;
}

.project-card__description {
  font-size: 11.5px;
  color: rgba(15, 23, 42, 0.5);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
  line-height: 1.55;
  margin-top: 3px;
}
</style>
