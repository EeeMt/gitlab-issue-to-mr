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
      <n-scrollbar class="template-drawer-layout__body" trigger="hover" content-style="padding: 8px 0;">
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
      </n-scrollbar>
    </div>
  </n-drawer>

  <!-- Schedule Heatmap Sub-Drawer (create mode only) -->
  <n-drawer v-if="mode === 'create'" v-model:show="showHeatmapDrawer" :width="isMobile ? '100%' : 580" placement="right">
    <n-drawer-content :title="t('createTask.schedulePreviewTitle')" :native-scrollbar="false" closable>
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
      :native-scrollbar="false"
      closable
    >
      <n-form label-placement="top" class="task-form-drawer__form">
        <section class="task-form-section task-form-section--content">
          <header class="task-form-section__header">
            <span class="task-form-section__title">{{ t('createTask.contentSection') }}</span>
            <span class="task-form-section__hint">{{ t('createTask.contentSectionHint') }}</span>
            <span class="task-form-section__divider" aria-hidden="true"></span>
          </header>
          <div class="task-form-section__body">
        <!-- Prompt + require changes -->
        <div class="prompt-form-section">
          <div class="prompt-section-header">
            <div class="prompt-label-left">
              <span class="prompt-section-label-text">{{ t('issue.prompt') }}</span>
              <n-button
                size="tiny"
                :disabled="promptTemplatesLoading || activePromptTemplates.length === 0"
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
        >
          <template #label>
            <div class="task-mode-label-row">
              <span>{{ t('issue.taskMode') }}</span>
              <span
                class="task-mode-label-hint"
                :class="{ 'task-mode-label-hint--error': taskModeErrorVisible }"
              >{{ t('issue.taskModeManualHint') }}</span>
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
                <Transition name="selection-check">
                  <n-icon
                    v-if="taskMode === 'execute'"
                    :component="CheckmarkCircleOutline"
                    size="16"
                    class="task-mode-card__check"
                  />
                </Transition>
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
                <Transition name="selection-check">
                  <n-icon
                    v-if="taskMode === 'plan'"
                    :component="CheckmarkCircleOutline"
                    size="16"
                    class="task-mode-card__check"
                  />
                </Transition>
              </div>
            </div>
            <Transition name="task-mode-detail">
              <div v-if="taskMode === 'execute'" class="task-mode-detail-reveal">
                <div class="task-mode-detail-reveal__inner">
                  <div class="require-changes-row">
                    <span class="prompt-label-require-text">{{ t('issue.requireChanges') }}</span>
                    <n-tooltip
                      trigger="hover"
                      placement="top"
                      :content-style="issueDetailTooltipContentStyle"
                      :theme-overrides="issueDetailTooltipThemeOverrides"
                    >
                      <template #trigger>
                        <n-icon :component="InformationCircleOutline" size="13" class="require-changes-info-icon" />
                      </template>
                      {{ t('issue.requireChangesHint') }}
                    </n-tooltip>
                    <n-switch v-model:value="requireChanges" size="small" />
                  </div>
                </div>
              </div>
            </Transition>
          </div>
        </n-form-item>

        <Transition name="advanced-option">
          <div v-if="taskMode !== null" class="run-instruction-advanced-reveal">
            <div class="run-instruction-advanced-reveal__inner">
              <div
                class="run-instruction-advanced"
                :class="{ 'run-instruction-advanced--open': runInstructionExpanded }"
              >
                <button
                  type="button"
                  class="run-instruction-advanced__summary"
                  :aria-expanded="runInstructionExpanded"
                  :aria-controls="runInstructionAdvancedContentId"
                  @click="runInstructionExpanded = !runInstructionExpanded"
                >
                  <span class="run-instruction-advanced__copy">
                    <span class="run-instruction-advanced__title">{{ t('runInstruction.advanced') }}</span>
                    <span class="run-instruction-advanced__hint">
                      {{ t('runInstruction.advancedHint') }}
                    </span>
                  </span>
                  <span class="run-instruction-advanced__chevron" aria-hidden="true">›</span>
                </button>
                <Transition name="advanced-content">
                  <div
                    v-if="runInstructionExpanded"
                    :id="runInstructionAdvancedContentId"
                    class="run-instruction-advanced__content-reveal"
                  >
                    <div class="run-instruction-advanced__content-reveal-inner">
                      <div class="run-instruction-advanced__content">
                        <n-spin :show="defaultsLoading">
                          <n-alert v-if="defaultsError" type="error" :bordered="false">
                            {{ defaultsError }}
                          </n-alert>
                          <div class="run-instruction-field">
                            <div class="run-instruction-header">
                              <span class="run-instruction-header__title">{{ t('runInstruction.template') }}</span>
                              <div class="run-instruction-header__actions">
                                <n-button size="tiny" quaternary @click="usePromptOnly">
                                  {{ t('runInstruction.usePromptOnly') }}
                                </n-button>
                                <n-button size="tiny" quaternary @click="restoreRunInstructionDefault">
                                  {{ t('runInstruction.restoreDefault') }}
                                </n-button>
                              </div>
                            </div>
                            <RunInstructionTemplateEditor
                              :model-value="runInstructionTemplate"
                              :available-placeholders="currentAvailablePlaceholders"
                              :known-placeholders="knownRunInstructionPlaceholders"
                              hide-actions
                              preview-enabled
                              :preview-loading="previewLoading"
                              :preview-result="previewResult"
                              :preview-error="previewError"
                              embedded
                              @update:model-value="handleRunInstructionInput"
                              @preview="handleRunInstructionPreview"
                            />
                          </div>
                        </n-spin>
                      </div>
                    </div>
                  </div>
                </Transition>
              </div>
            </div>
          </div>
        </Transition>
          </div>
        </section>

        <section class="task-form-section task-form-section--execution">
          <header class="task-form-section__header">
            <span class="task-form-section__title">{{ t('createTask.executionSection') }}</span>
            <span class="task-form-section__hint">
              {{ t(mode === 'create'
                ? 'createTask.executionSectionHint'
                : 'createTask.executionSectionEditHint') }}
            </span>
            <span class="task-form-section__divider" aria-hidden="true"></span>
          </header>
          <div class="task-form-section__body">
        <!-- Priority cards -->
        <n-form-item
          :label="t('common.priority')"
          class="priority-form-item"
          :class="{ 'priority-form-item--last': mode !== 'create' }"
        >
          <div class="priority-selector" role="radiogroup" :aria-label="t('common.priority')">
            <div
              v-for="opt in priorityOptions"
              :key="opt.value"
              class="priority-card"
              role="radio"
              tabindex="0"
              :aria-checked="priority === opt.value"
              :class="[
                `priority-card--p${opt.value}`,
                { 'priority-card--active': priority === opt.value }
              ]"
              @click="priority = opt.value"
              @keydown.enter.prevent="priority = opt.value"
              @keydown.space.prevent="priority = opt.value"
            >
              <div>
                <div class="priority-card__label">{{ opt.label }}</div>
                <div class="priority-card__desc">{{ opt.desc }}</div>
              </div>
              <Transition name="selection-check">
                <n-icon
                  v-if="priority === opt.value"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="priority-card__check"
                />
              </Transition>
            </div>
          </div>
        </n-form-item>

        <!-- Schedule (create mode only) -->
        <n-form-item v-if="mode === 'create'" class="schedule-form-item">
          <template #label>
            <div class="execution-field-label">
              <span>{{ t('createTask.schedule') }}</span>
              <span class="execution-field-label__hint">{{ t('createTask.scheduleHint') }}</span>
            </div>
          </template>
          <div class="schedule-section">
            <div class="schedule-mode-selector" role="radiogroup" :aria-label="t('createTask.schedule')">
              <button
                type="button"
                class="schedule-mode-card"
                :class="{ 'schedule-mode-card--active': scheduleType === 'now' }"
                role="radio"
                :aria-checked="scheduleType === 'now'"
                @click="selectScheduleType('now')"
              >
                <span class="schedule-mode-card__icon">
                  <n-icon :component="FlashOutline" size="17" />
                </span>
                <span class="schedule-mode-card__copy">
                  <span class="schedule-mode-card__title">{{ t('createTask.executeNow') }}</span>
                  <span class="schedule-mode-card__description">{{ t('createTask.executeNowDesc') }}</span>
                </span>
                <n-icon
                  v-if="scheduleType === 'now'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="schedule-mode-card__check"
                />
              </button>
              <button
                type="button"
                class="schedule-mode-card"
                :class="{ 'schedule-mode-card--active': scheduleType === 'scheduled' }"
                role="radio"
                :aria-checked="scheduleType === 'scheduled'"
                @click="selectScheduleType('scheduled')"
              >
                <span class="schedule-mode-card__icon">
                  <n-icon :component="TimeOutline" size="17" />
                </span>
                <span class="schedule-mode-card__copy">
                  <span class="schedule-mode-card__title">{{ t('createTask.scheduleAt') }}</span>
                  <span class="schedule-mode-card__description">{{ t('createTask.scheduleAtDesc') }}</span>
                </span>
                <n-icon
                  v-if="scheduleType === 'scheduled'"
                  :component="CheckmarkCircleOutline"
                  size="16"
                  class="schedule-mode-card__check"
                />
              </button>
            </div>
            <Transition name="schedule-detail">
              <div v-if="scheduleType === 'scheduled'" class="schedule-detail-reveal">
                <div class="schedule-detail-reveal__inner">
                  <div class="schedule-detail-panel">
                    <n-date-picker
                      v-model:value="scheduledAt"
                      class="schedule-detail-panel__picker"
                      type="datetime"
                      clearable
                      :placeholder="t('createTask.selectDateTime')"
                      :is-date-disabled="isScheduleDateDisabled"
                    />
                    <n-button
                      class="schedule-detail-panel__heatmap"
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
              </div>
            </Transition>
          </div>
        </n-form-item>

        <n-form-item
          v-if="mode === 'create'"
          :label="t('createTask.sessionContext')"
          class="session-context-form-item"
        >
          <div
            class="session-context-row"
            :class="{ 'session-context-row--active': startFreshSession }"
            data-testid="task-session-mode"
          >
            <span class="session-context-row__copy">
              <span class="session-context-row__heading">
                <span class="session-context-row__title">{{ t('createTask.startFreshSession') }}</span>
                <n-switch
                  v-model:value="startFreshSession"
                  size="small"
                  data-testid="task-session-mode-switch"
                />
              </span>
              <span class="session-context-row__description">
                {{ t(hasClaudeSession
                  ? 'createTask.startFreshSessionHint'
                  : 'createTask.startFreshSessionNoCurrent') }}
              </span>
            </span>
          </div>
        </n-form-item>
          </div>
        </section>

        <!-- Execution environment -->
        <section class="task-form-section task-form-section--environment">
          <header class="task-form-section__header">
            <span class="task-form-section__title">{{ t('createTask.executionEnvironment') }}</span>
            <span class="task-form-section__hint">
              {{ t('createTask.executionEnvironmentHint') }}
            </span>
            <span class="task-form-section__divider" aria-hidden="true"></span>
          </header>
          <div
            class="execution-environment"
            :class="{
              'execution-environment--open': executionEnvironmentOpen,
              'execution-environment--warning': executionEnvironmentMissing
            }"
          >
            <button
              type="button"
              class="execution-environment__summary"
              :aria-expanded="executionEnvironmentOpen"
              :aria-controls="executionEnvironmentContentId"
              @click="toggleExecutionEnvironment"
            >
              <span class="execution-environment__copy">
                <span
                  class="execution-environment__status"
                  :class="{
                    'execution-environment__status--override': executionEnvironmentOverridden,
                    'execution-environment__status--warning': executionEnvironmentMissing
                  }"
                >
                  {{ executionEnvironmentMissing
                    ? t('createTask.executionEnvironmentNeedsAttention')
                    : executionEnvironmentOverridden
                      ? t('createTask.executionEnvironmentOverride')
                      : t('createTask.executionEnvironmentDefault') }}
                </span>
                <span class="execution-environment__meta">
                  <span v-if="!executionOptionsReady">{{ t('common.loading') }}</span>
                  <template v-else>
                    <span>{{ effectiveWorkerProfile?.name ?? t('common.unavailable') }}</span>
                    <span aria-hidden="true">·</span>
                    <span>
                      {{ effectiveProvider
                        ? `${effectiveProvider.name} / ${effectiveProvider.model}`
                        : t('common.unavailable') }}
                    </span>
                  </template>
                </span>
              </span>
              <span class="execution-environment__action">
                <span>{{ executionEnvironmentMissing
                  ? t('createTask.executionEnvironmentConfigure')
                  : executionEnvironmentOpen
                    ? t('createTask.executionEnvironmentCollapse')
                    : t('createTask.executionEnvironmentChange') }}</span>
                <span class="execution-environment__chevron" aria-hidden="true">›</span>
              </span>
            </button>
            <Transition name="execution-environment-detail">
              <div
                v-if="executionEnvironmentOpen"
                :id="executionEnvironmentContentId"
                class="execution-environment__detail-reveal"
              >
                <div class="execution-environment__detail-reveal-inner">
                  <div class="execution-environment__detail">
                    <div v-if="executionEnvironmentMissing" class="execution-environment__warning">
                      {{ t('createTask.executionEnvironmentMissing') }}
                    </div>
                    <div class="execution-environment__fields">
                      <label class="execution-environment__field">
                        <span>{{ t('createTask.workerProfile') }}</span>
                        <n-input
                          :value="effectiveWorkerProfile?.name ?? t('common.unavailable')"
                          disabled
                        />
                      </label>
                      <label class="execution-environment__field">
                        <span>{{ t('config.providers.providerLabel') }}</span>
                        <n-select
                          v-model:value="selectedProviderId"
                          :options="providerOptions"
                          clearable
                          :placeholder="t('createTask.selectProvider')"
                        />
                      </label>
                    </div>
                    <div v-if="executionEnvironmentOverridden" class="execution-environment__footer">
                      <n-button size="tiny" quaternary @click="restoreExecutionEnvironmentDefaults">
                        {{ t('createTask.executionEnvironmentRestore') }}
                      </n-button>
                    </div>
                  </div>
                </div>
              </div>
            </Transition>
          </div>
        </section>
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
import { ref, computed, watch, onMounted, toRef, useAttrs, useId } from 'vue'
import {
  NButton, NDrawer, NDrawerContent, NForm, NFormItem,
  NDatePicker, NInput, NSelect, NAlert, NTooltip, NSwitch, NSpin, NIcon, NScrollbar, NTag,
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
  CheckmarkCircleOutline,
  FlashOutline,
  TimeOutline
} from '@vicons/ionicons5'
import VariableEditor from './VariableEditor.vue'
import HeatmapChart from './HeatmapChart.vue'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'
import {
  getRunInstructionTemplateDefaults,
  type Task, type RunInstructionTemplateDefaults
} from '../api'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, formatTimeUtc8 } from '../utils/datetime'
import { formatUsageResetAt } from '../utils/usageLimits'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './issue-detail/tooltip'
import {
  DEFAULT_REQUIRE_CHANGES,
  DEFAULT_TASK_PRIORITY,
} from '../features/tasks/taskFormModel'
import { useTaskScheduleContext } from '../features/tasks/useTaskScheduleContext'
import { usePromptTemplatePicker } from '../features/tasks/usePromptTemplatePicker'
import { useTaskExecutionOptions } from '../features/tasks/useTaskExecutionOptions'
import { useRunInstructionPreview } from '../features/tasks/useRunInstructionPreview'
import { useTaskSlotCapacity } from '../features/tasks/useTaskSlotCapacity'
import { useTaskFormSubmission } from '../features/tasks/useTaskFormSubmission'

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  show: boolean
  mode?: 'create' | 'edit'
  issueId?: number
  issueDescription?: string
  hasClaudeSession?: boolean
  workerProfileId?: number | null
  defaultProviderId?: number | null
  task?: Task
}>(), {
  mode: 'create',
  hasClaudeSession: false
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [task: Task]
  updated: [task: Task]
}>()

const { t } = useI18n()
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
const priority = ref(DEFAULT_TASK_PRIORITY)
const requireChanges = ref(DEFAULT_REQUIRE_CHANGES)
const taskMode = ref<'execute' | 'plan' | null>(null)
const startFreshSession = ref(false)
const taskModeErrorVisible = ref(false)
const runInstructionExpanded = ref(false)
const runInstructionAdvancedContentId = `${useId()}-run-instruction-advanced-content`
const executionEnvironmentExpanded = ref(false)
const executionEnvironmentContentId = `${useId()}-execution-environment-content`
const executionOptionsReady = ref(false)
const selectedProviderId = ref<number | null>(null)
const scheduleType = ref<'now' | 'scheduled'>('now')
const scheduledAt = ref<number | null>(null)
const runInstructionTemplate = ref('')
const initialRunInstructionTemplate = ref('')
const runInstructionDirty = ref(false)
const runInstructionDefaults = ref<RunInstructionTemplateDefaults | null>(null)
const defaultsLoading = ref(false)
const defaultsError = ref('')
const {
  handleRunInstructionPreview,
  invalidateRunInstructionPreview,
  previewError,
  previewLoading,
  previewResult,
} = useRunInstructionPreview({
  issueId: toRef(props, 'issueId'),
  task: toRef(props, 'task'),
  taskMode,
  prompt,
  issueDescription: toRef(props, 'issueDescription'),
  runInstructionTemplate,
  requireChanges,
})

const {
  activePromptTemplates,
  cancelTemplateOverwrite,
  confirmTemplateOverwrite,
  filteredPromptTemplates,
  handleTemplateItemClick,
  handleTemplateTagFilterUpdate,
  loadTemplates,
  pendingTemplate,
  promptTemplatesLoading,
  promptVariableTips,
  selectedTemplateTags,
  showTemplateDrawer,
  templateTagFilterVisible,
  templateTagOptions,
} = usePromptTemplatePicker(prompt)

const {
  effectiveProvider,
  effectiveWorkerProfile,
  loadProviders,
  loadWorkerProfiles,
  providerOptions,
} = useTaskExecutionOptions({
  mode: toRef(props, 'mode'),
  task: toRef(props, 'task'),
  defaultProviderId: toRef(props, 'defaultProviderId'),
  workerProfileId: toRef(props, 'workerProfileId'),
  selectedProviderId,
})
const executionEnvironmentMissing = computed(() =>
  executionOptionsReady.value
  && (!effectiveWorkerProfile.value || !effectiveProvider.value)
)
const executionEnvironmentOverridden = computed(() =>
  selectedProviderId.value !== null
)
const executionEnvironmentOpen = computed(() =>
  executionEnvironmentExpanded.value || executionEnvironmentMissing.value
)

// Schedule heatmap state (create mode)
const showHeatmapDrawer = ref(false)
const {
  scheduledTasks: scheduledTasksForPreview,
  scheduledTasksLoading,
  slotMaxTasks,
  slotEnforce,
  loadScheduleContext,
  clearScheduledTasks,
} = useTaskScheduleContext()
const {
  slotCapacity,
  slotCapacityLoading,
} = useTaskSlotCapacity({
  scheduledAt,
  enabled: computed(() => props.mode === 'create'),
})
defineExpose({ slotCapacityLoading })

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

const currentAvailablePlaceholders = computed(() => {
  if (!runInstructionDefaults.value || !taskMode.value) return []
  return runInstructionDefaults.value[taskMode.value].available_placeholders
})
const knownRunInstructionPlaceholders = computed(() => [
  ...new Set(runInstructionDefaults.value?.execute.known_placeholders ?? [
    ...(runInstructionDefaults.value?.execute.available_placeholders ?? []),
    ...(runInstructionDefaults.value?.plan.available_placeholders ?? [])
  ])
])

// --- Watchers ---
watch(scheduleType, (val) => {
  if (val === 'now') scheduledAt.value = null
})

watch(taskMode, (val) => {
  invalidateRunInstructionPreview()
  if (val !== null) {
    taskModeErrorVisible.value = false
    if (!runInstructionTemplate.value && runInstructionDefaults.value) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(val)
    }
  }
}, { flush: 'sync' })

watch([prompt, requireChanges], () => {
  invalidateRunInstructionPreview()
}, { flush: 'sync' })

watch(() => props.show, (val) => {
  invalidateRunInstructionPreview()
  runInstructionExpanded.value = false
  executionEnvironmentExpanded.value = false
  if (val) {
    if (props.mode === 'edit' && props.task) {
      prompt.value = props.task.user_prompt ?? ''
      priority.value = props.task.priority ?? DEFAULT_TASK_PRIORITY
      requireChanges.value = props.task.require_changes ?? true
      taskMode.value = (props.task.task_mode as 'execute' | 'plan') ?? 'execute'
      selectedProviderId.value = props.task.provider_id ?? null
      const snapshot = props.task.run_instruction_template
        ?? getDefaultRunInstructionTemplate(taskMode.value)
        ?? ''
      runInstructionTemplate.value = snapshot
      initialRunInstructionTemplate.value = snapshot
      runInstructionDirty.value = false
    } else if (props.mode === 'create') {
      if (!prompt.value && props.issueDescription) {
        prompt.value = props.issueDescription
      }
      taskMode.value = null
      selectedProviderId.value = null
      runInstructionTemplate.value = ''
      initialRunInstructionTemplate.value = ''
      runInstructionDirty.value = false
      requireChanges.value = DEFAULT_REQUIRE_CHANGES
      startFreshSession.value = false
      scheduleType.value = 'now'
      scheduledAt.value = null
      void loadScheduleContext()
    }
    usageLimitDetail.value = null
    taskModeErrorVisible.value = false
  }
})

// --- Data loading ---
async function loadRunInstructionDefaults() {
  defaultsLoading.value = true
  defaultsError.value = ''
  try {
    runInstructionDefaults.value = await getRunInstructionTemplateDefaults()
    if (props.show && props.mode === 'edit' && props.task && !runInstructionTemplate.value) {
      const mode = (props.task.task_mode ?? 'execute') as 'execute' | 'plan'
      const snapshot = props.task.run_instruction_template ?? getDefaultRunInstructionTemplate(mode)
      runInstructionTemplate.value = snapshot
      initialRunInstructionTemplate.value = snapshot
    }
    if (props.show && props.mode === 'create' && taskMode.value && !runInstructionTemplate.value) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
      initialRunInstructionTemplate.value = runInstructionTemplate.value
    }
  } catch {
    defaultsError.value = t('runInstruction.defaultsLoadFailed')
  } finally {
    defaultsLoading.value = false
  }
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

function selectScheduleType(type: 'now' | 'scheduled') {
  scheduleType.value = type
}

function selectTaskMode(mode: 'execute' | 'plan') {
  if (taskMode.value === mode) return
  const nextDefault = getDefaultRunInstructionTemplate(mode)
  if (runInstructionDirty.value && runInstructionTemplate.value) {
    const replace = window.confirm(t('runInstruction.modeSwitchConfirm'))
    if (replace) runInstructionTemplate.value = nextDefault
  } else {
    runInstructionTemplate.value = nextDefault
  }
  taskMode.value = mode
}

function handleRunInstructionInput(value: string) {
  runInstructionTemplate.value = value
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function restoreRunInstructionDefault() {
  if (!taskMode.value) return
  runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function getDefaultRunInstructionTemplate(mode: 'execute' | 'plan' | null): string {
  if (!mode) return ''
  const profile = effectiveWorkerProfile.value
  if (profile) {
    return mode === 'plan'
      ? profile.default_plan_run_instruction_template
      : profile.default_execute_run_instruction_template
  }
  return runInstructionDefaults.value?.[mode].content ?? ''
}

function toggleExecutionEnvironment() {
  if (executionEnvironmentMissing.value) {
    executionEnvironmentExpanded.value = true
    return
  }
  executionEnvironmentExpanded.value = !executionEnvironmentExpanded.value
}

function restoreExecutionEnvironmentDefaults() {
  selectedProviderId.value = null
  if (!executionEnvironmentMissing.value) {
    executionEnvironmentExpanded.value = false
  }
}

async function loadExecutionOptions() {
  executionOptionsReady.value = false
  await Promise.all([loadProviders(), loadWorkerProfiles()])
  executionOptionsReady.value = true
}

function usePromptOnly() {
  runInstructionTemplate.value = '{{user_prompt}}'
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  return candidate.getTime() < today.getTime()
}

const {
  handleCreate,
  handleEdit,
  submitLoading,
  usageLimitDetail,
} = useTaskFormSubmission({
  issueId: toRef(props, 'issueId'),
  task: toRef(props, 'task'),
  prompt,
  priority,
  requireChanges,
  taskMode,
  startFreshSession,
  taskModeErrorVisible,
  selectedProviderId,
  scheduleType,
  scheduledAt,
  runInstructionTemplate,
  initialRunInstructionTemplate,
  runInstructionDirty,
  defaultsError,
  getDefaultRunInstructionTemplate,
  clearScheduledTasks,
  close: () => emit('update:show', false),
  created: task => emit('created', task),
  updated: task => emit('updated', task),
})

// --- Lifecycle ---
onMounted(() => {
  void loadExecutionOptions()
  void loadTemplates()
  void loadRunInstructionDefaults()
})
</script>

<style scoped>
.run-instruction-field {
  display: grid;
  gap: 4px;
}

.run-instruction-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.run-instruction-header__title {
  font-weight: var(--n-label-font-weight, 400);
  font-size: var(--n-label-font-size, 14px);
  color: var(--n-label-text-color, var(--n-text-color-1));
}

.run-instruction-header__actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-form-drawer__form {
  max-width: 100%;
}

.task-form-section {
  width: 100%;
}

.task-form-section + .task-form-section {
  margin-top: 24px;
}

.task-form-section__header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  min-width: 0;
  margin-bottom: 12px;
}

.task-form-section__title {
  flex: 0 0 auto;
  color: var(--n-text-color-1, var(--n-text-color));
  font-size: 13px;
  font-weight: 600;
  line-height: 20px;
}

.task-form-section__hint {
  flex: 0 1 auto;
  min-width: 0;
  overflow: hidden;
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 400;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-form-section__divider {
  flex: 1 1 auto;
  min-width: 20px;
  height: 1px;
  background: var(--n-border-color);
  opacity: 0.72;
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

.task-mode-label-hint--error {
  color: var(--n-feedback-text-color-error, #d03050);
}

.task-mode-section {
  display: flex;
  flex-direction: column;
  width: 100%;
  gap: 0;
}

.task-mode-form-item {
  margin-bottom: 12px;
}

.run-instruction-advanced {
  width: 100%;
  overflow: hidden;
  border: 1px solid rgba(128, 128, 128, 0.28);
  border-radius: 10px;
  background: rgba(128, 128, 128, 0.025);
  transition: border-color 0.15s ease, box-shadow 0.15s ease;
}

.run-instruction-advanced-reveal {
  display: grid;
  grid-template-rows: 1fr;
  margin-bottom: 16px;
  opacity: 1;
  transform: translateY(0);
}

.task-form-section--content .run-instruction-advanced-reveal {
  margin-bottom: 0;
}

.run-instruction-advanced-reveal__inner,
.run-instruction-advanced__content-reveal-inner {
  min-height: 0;
}

.run-instruction-advanced__content-reveal-inner,
.advanced-option-enter-active .run-instruction-advanced-reveal__inner,
.advanced-option-leave-active .run-instruction-advanced-reveal__inner {
  overflow: hidden;
}

.advanced-option-enter-active,
.advanced-option-leave-active {
  transition:
    grid-template-rows 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    margin-bottom 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.14s ease,
    transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.advanced-option-enter-from,
.advanced-option-leave-to {
  grid-template-rows: 0fr;
  margin-bottom: 0;
  opacity: 0;
  transform: translateY(-4px);
}

.run-instruction-advanced--open {
  border-color: var(--n-primary-color);
  box-shadow: 0 0 0 2px rgba(99, 226, 183, 0.06);
}

.run-instruction-advanced__summary {
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  min-height: 48px;
  padding: 8px 12px;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
  user-select: none;
}

.run-instruction-advanced__copy {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.run-instruction-advanced__title {
  color: var(--n-text-color);
  font-size: 14px;
  font-weight: 600;
  line-height: 20px;
}

.run-instruction-advanced__hint {
  overflow: hidden;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 18px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.run-instruction-advanced__chevron {
  color: var(--n-text-color-3);
  font-size: 22px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.15s ease, color 0.15s ease;
}

.run-instruction-advanced--open .run-instruction-advanced__chevron {
  color: var(--n-primary-color);
  transform: rotate(90deg);
}

.run-instruction-advanced__content-reveal {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
}

.advanced-content-enter-active,
.advanced-content-leave-active {
  transition:
    grid-template-rows 0.22s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.16s ease;
}

.advanced-content-enter-from,
.advanced-content-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.run-instruction-advanced__content {
  padding: 12px 12px 4px;
  border-top: 1px solid var(--n-border-color);
  background: rgba(255, 255, 255, 0.015);
}

@media (hover: hover) and (pointer: fine) {
  .run-instruction-advanced:not(.run-instruction-advanced--open):hover {
    border-color: var(--n-primary-color);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-instruction-advanced,
  .run-instruction-advanced__chevron,
  .task-mode-card,
  .task-mode-card__icon,
  .selection-check-enter-active,
  .selection-check-leave-active,
  .task-mode-detail-enter-active,
  .task-mode-detail-leave-active,
  .advanced-option-enter-active,
  .advanced-option-leave-active,
  .advanced-content-enter-active,
  .advanced-content-leave-active {
    transition: none;
  }
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
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
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
  transition: color 0.15s ease;
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

.selection-check-enter-active,
.selection-check-leave-active {
  transition: opacity 0.14s ease, transform 0.14s ease;
}

.selection-check-enter-from,
.selection-check-leave-to {
  opacity: 0;
  transform: scale(0.72);
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
  padding-left: 12px;
}

.task-mode-detail-reveal {
  display: grid;
  grid-template-rows: 1fr;
  margin-top: 8px;
  opacity: 1;
  transform: translateY(0);
}

.task-mode-detail-reveal__inner {
  min-height: 0;
  overflow: hidden;
}

.task-mode-detail-enter-active,
.task-mode-detail-leave-active {
  transition:
    grid-template-rows 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    margin-top 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.14s ease,
    transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-mode-detail-enter-from,
.task-mode-detail-leave-to {
  grid-template-rows: 0fr;
  margin-top: 0;
  opacity: 0;
  transform: translateY(-4px);
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
.priority-form-item {
  margin-bottom: 18px;
}

.priority-form-item--last,
.session-context-form-item {
  margin-bottom: 0;
}

.schedule-form-item {
  margin-bottom: 18px;
}

.session-context-row {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.035);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.session-context-row--active {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.06);
}

.session-context-row__copy {
  display: flex;
  flex-direction: column;
  gap: 2px;
  width: 100%;
  min-width: 0;
}

.session-context-row__heading {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.session-context-row__heading :deep(.n-switch) {
  flex: 0 0 auto;
}

.session-context-row__title {
  color: var(--n-text-color-1);
  font-size: 13px;
  font-weight: 600;
  line-height: 20px;
}

.session-context-row__description {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 1.45;
}

.priority-selector {
  display: flex;
  gap: 8px;
  width: 100%;
}

.priority-card {
  position: relative;
  flex: 1;
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  padding: 8px 32px 8px 12px;
  border: 1px solid var(--n-border-color);
  border-radius: 8px;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
}

.priority-card:focus-visible {
  outline: 2px solid var(--n-primary-color);
  outline-offset: 2px;
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

.priority-card__check {
  position: absolute;
  top: 8px;
  right: 9px;
  color: currentColor;
}

.priority-card--p0 .priority-card__check { color: #d03050; }
.priority-card--p1 .priority-card__check { color: #f0a020; }
.priority-card--p2 .priority-card__check { color: #18a058; }

/* Execution fields */
.execution-field-label {
  display: inline-flex;
  align-items: baseline;
  gap: 8px;
}

.execution-field-label__hint {
  color: var(--n-text-color-3);
  font-size: 12px;
  font-weight: 400;
}

/* Schedule section */
.schedule-section {
  display: flex;
  flex-direction: column;
  width: 100%;
}

.schedule-mode-selector {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
  width: 100%;
}

.schedule-mode-card {
  position: relative;
  display: flex;
  align-items: flex-start;
  gap: 10px;
  width: 100%;
  min-width: 0;
  min-height: 66px;
  padding: 10px 32px 10px 11px;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: var(--n-color);
  color: var(--n-text-color);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.15s ease, background-color 0.15s ease, transform 0.15s ease;
}

.schedule-mode-card--active {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.06);
}

.schedule-mode-card:focus-visible {
  outline: 2px solid var(--n-primary-color);
  outline-offset: 2px;
}

.schedule-mode-card__icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 30px;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: rgba(128, 128, 128, 0.09);
  color: var(--n-text-color-3);
  transition: color 0.15s ease, background-color 0.15s ease;
}

.schedule-mode-card--active .schedule-mode-card__icon {
  background: rgba(99, 226, 183, 0.12);
  color: var(--n-primary-color);
}

.schedule-mode-card__copy {
  display: flex;
  flex: 1;
  flex-direction: column;
  min-width: 0;
}

.schedule-mode-card__title {
  font-size: 13px;
  font-weight: 600;
  line-height: 20px;
}

.schedule-mode-card__description {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.schedule-mode-card__check {
  position: absolute;
  top: 10px;
  right: 10px;
  color: var(--n-primary-color);
}

.schedule-detail-panel {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: rgba(128, 128, 128, 0.035);
}

.schedule-detail-panel__picker {
  flex: 1;
  min-width: 0;
}

.schedule-detail-panel__heatmap {
  flex-shrink: 0;
}

.schedule-detail-reveal {
  display: grid;
  grid-template-rows: 1fr;
  margin-top: 10px;
  opacity: 1;
  transform: translateY(0);
}

.schedule-detail-enter-active,
.schedule-detail-leave-active {
  transition:
    grid-template-rows 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    margin-top 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.14s ease,
    transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.schedule-detail-enter-from,
.schedule-detail-leave-to {
  grid-template-rows: 0fr;
  margin-top: 0;
  opacity: 0;
  transform: translateY(-4px);
}

.schedule-detail-reveal__inner {
  min-height: 0;
  overflow: hidden;
}

/* Execution environment */
.execution-environment {
  width: 100%;
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: rgba(128, 128, 128, 0.035);
  transition: border-color 0.15s ease, background-color 0.15s ease;
}

.execution-environment--open,
.execution-environment:focus-within {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.04);
}

.execution-environment--warning {
  border-color: rgba(240, 160, 32, 0.55);
  background: rgba(240, 160, 32, 0.035);
}

.execution-environment__summary {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 46px;
  padding: 8px 10px;
  border: 0;
  color: inherit;
  background: transparent;
  font: inherit;
  text-align: left;
  cursor: pointer;
}

.execution-environment__summary:focus-visible {
  outline: 2px solid var(--n-primary-color);
  outline-offset: -2px;
}

.execution-environment__copy {
  display: flex;
  align-items: center;
  min-width: 0;
  gap: 8px;
}

.execution-environment__status {
  padding: 1px 6px;
  border-radius: 999px;
  color: var(--n-text-color-3);
  background: var(--n-action-color);
  font-size: 10px;
  line-height: 16px;
  white-space: nowrap;
}

.execution-environment__status--override {
  color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.1);
}

.execution-environment__status--warning {
  color: #f0a020;
  background: rgba(240, 160, 32, 0.1);
}

.execution-environment__meta {
  display: flex;
  align-items: center;
  gap: 5px;
  min-width: 0;
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
  white-space: nowrap;
}

.execution-environment__meta > span:not([aria-hidden]) {
  overflow: hidden;
  text-overflow: ellipsis;
}

.execution-environment__action {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: var(--n-text-color-3);
  font-size: 11px;
  white-space: nowrap;
}

.execution-environment__chevron {
  color: var(--n-text-color-3);
  font-size: 18px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.16s ease, color 0.16s ease;
}

.execution-environment--open .execution-environment__chevron {
  color: var(--n-primary-color);
  transform: rotate(90deg);
}

.execution-environment__detail-reveal {
  display: grid;
  grid-template-rows: 1fr;
  opacity: 1;
}

.execution-environment__detail-reveal-inner {
  min-height: 0;
  overflow: hidden;
}

.execution-environment-detail-enter-active,
.execution-environment-detail-leave-active {
  transition:
    grid-template-rows 0.2s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.15s ease;
}

.execution-environment-detail-enter-from,
.execution-environment-detail-leave-to {
  grid-template-rows: 0fr;
  opacity: 0;
}

.execution-environment__detail {
  padding: 10px;
  border-top: 1px solid var(--n-border-color);
  background: var(--n-color);
}

.execution-environment__warning {
  margin-bottom: 9px;
  padding: 7px 9px;
  border-radius: 6px;
  color: #f0a020;
  background: rgba(240, 160, 32, 0.08);
  font-size: 11px;
  line-height: 17px;
}

.execution-environment__fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.execution-environment__field {
  display: grid;
  gap: 5px;
  min-width: 0;
}

.execution-environment__field > span {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.execution-environment__footer {
  display: flex;
  justify-content: flex-end;
  margin-top: 6px;
}

@media (hover: hover) and (pointer: fine) {
  .priority-card:not(.priority-card--active):hover,
  .schedule-mode-card:not(.schedule-mode-card--active):hover,
  .execution-environment:not(.execution-environment--warning):hover {
    border-color: var(--n-primary-color);
  }

  .priority-card:not(.priority-card--active):hover,
  .schedule-mode-card:not(.schedule-mode-card--active):hover {
    transform: translateY(-1px);
  }
}

@media (max-width: 520px) {
  .task-form-section__header {
    align-items: flex-start;
    flex-wrap: wrap;
    gap: 2px 8px;
  }

  .task-form-section__divider {
    flex-basis: 100%;
  }

  .schedule-mode-selector {
    grid-template-columns: 1fr;
  }

  .schedule-detail-panel {
    align-items: stretch;
    flex-direction: column;
  }

  .execution-environment__fields {
    grid-template-columns: 1fr;
  }

  .execution-environment__meta {
    align-items: flex-start;
    flex-direction: column;
    gap: 0;
    white-space: normal;
  }

  .execution-environment__meta > span[aria-hidden] {
    display: none;
  }

  .execution-environment__copy {
    align-items: flex-start;
    flex-direction: column;
    gap: 2px;
  }

  .schedule-detail-panel__heatmap {
    width: 100%;
  }

  .execution-field-label {
    align-items: flex-start;
    flex-direction: column;
    gap: 1px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .priority-card,
  .schedule-mode-card,
  .schedule-mode-card__icon,
  .execution-environment,
  .execution-environment__chevron,
  .execution-environment-detail-enter-active,
  .execution-environment-detail-leave-active,
  .schedule-detail-enter-active,
  .schedule-detail-leave-active {
    transition: none;
  }
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
  min-height: 0;
}

.template-tag-filter {
  padding: 8px 16px 12px;
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
