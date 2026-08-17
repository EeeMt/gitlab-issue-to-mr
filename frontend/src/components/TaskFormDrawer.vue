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
      <section
        v-show="isModeChoiceVisible"
        ref="modeChoicePanelRef"
        class="task-mode-choice"
        :class="{ 'task-form-view--active': isModeChoiceVisible }"
        data-testid="task-mode-choice"
        :aria-hidden="!isModeChoiceVisible"
        :inert="!isModeChoiceVisible"
      >
          <header class="task-mode-choice__header">
            <h2 class="task-mode-choice__title">{{ t('issue.taskModeChoiceTitle') }}</h2>
            <p class="task-mode-choice__hint">{{ t('issue.taskModeChoiceHint') }}</p>
          </header>
          <div class="task-mode-choice__list" role="radiogroup" :aria-label="t('issue.taskMode')">
            <button
              v-for="option in taskModeOptions"
              :key="option.mode"
              type="button"
              class="task-mode-choice__option"
              :class="{ 'task-mode-choice__option--active': taskMode === option.mode }"
              role="radio"
              :aria-checked="taskMode === option.mode"
              :data-task-mode="option.mode"
              :data-testid="`task-mode-option-${option.mode}`"
              @click="selectTaskMode(option.mode)"
              @keydown.enter.prevent="selectTaskMode(option.mode)"
              @keydown.space.prevent="selectTaskMode(option.mode)"
            >
              <span class="task-mode-choice__icon" aria-hidden="true">
                <n-icon :component="option.icon" size="20" />
              </span>
              <span class="task-mode-choice__copy">
                <span class="task-mode-choice__label">{{ option.label }}</span>
                <span class="task-mode-choice__description">{{ option.description }}</span>
              </span>
              <n-icon
                v-if="taskMode === option.mode"
                :component="CheckmarkCircleOutline"
                size="18"
                class="task-mode-choice__check"
              />
            </button>
          </div>
      </section>

      <div
        v-show="isFullFormVisible"
        ref="fullFormPanelRef"
        class="task-full-form"
        :class="{ 'task-form-view--active': isFullFormVisible }"
        data-testid="task-full-form"
        :aria-hidden="!isFullFormVisible"
        :inert="!isFullFormVisible"
      >
      <n-form label-placement="top" class="task-form-drawer__form">
        <div v-if="currentTaskModeOption" class="task-mode-summary" data-testid="task-mode-summary">
          <span class="task-mode-summary__icon" aria-hidden="true">
            <n-icon :component="currentTaskModeOption.icon" size="18" />
          </span>
          <span class="task-mode-summary__copy">
            <span class="task-mode-summary__label">{{ currentTaskModeOption.label }}</span>
            <span class="task-mode-summary__separator" aria-hidden="true">·</span>
            <span class="task-mode-summary__description">{{ currentTaskModeOption.summary }}</span>
          </span>
          <n-button
            quaternary
            size="small"
            class="task-mode-summary__change"
            data-testid="task-mode-change"
            @click="changeTaskMode"
          >
            {{ t('issue.changeTaskMode') }}
          </n-button>
        </div>
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

        <Transition name="task-mode-detail" :css="taskModeDetailTransitionEnabled">
          <div
            v-if="taskMode === 'execute'"
            class="task-mode-detail-reveal"
            data-testid="task-require-changes"
          >
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

        <Transition name="advanced-option" :css="taskModeDetailTransitionEnabled">
          <div v-if="taskMode !== null && taskMode !== 'freeform'" class="run-instruction-advanced-reveal">
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
                      :is-time-disabled="isTimeDisabled"
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
                  <p v-if="createScheduleConstraintHint" class="schedule-detail-panel__constraint">
                    {{ createScheduleConstraintHint }}
                  </p>
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
              'execution-environment--warning': executionEnvironmentNeedsAttention
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
                    'execution-environment__status--warning': executionEnvironmentNeedsAttention
                  }"
                >
                  {{ executionEnvironmentNeedsAttention
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
                <span>{{ executionEnvironmentNeedsAttention
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
                        <div class="execution-environment__field-hint" data-testid="task-worker-profile-hint">
                          {{ t('createTask.workerProfileLockedHint') }}
                        </div>
                      </label>
                      <label class="execution-environment__field">
                        <span>{{ t('config.providers.providerLabel') }}</span>
                        <n-select
                          :value="selectedProviderId"
                          :options="providerOptions"
                          clearable
                          :placeholder="t('createTask.selectProvider')"
                          :render-label="renderProviderLabel"
                          :menu-props="{ class: 'task-provider-select-menu' }"
                          class="task-provider-select"
                          @update:value="handleProviderChange"
                        />
                        <div
                          v-if="providerAutoAdjusted"
                          class="execution-environment__field-hint"
                          data-testid="task-provider-auto-adjusted-hint"
                        >
                          {{ t('createTask.providerAutoAdjustedHint') }}
                        </div>
                      </label>
                      <label v-if="harnessOptions.length > 1" class="execution-environment__field">
                        <span>{{ t('createTask.harness') }}</span>
                        <n-select
                          v-model:value="harnessKey"
                          :options="harnessOptions"
                          :placeholder="t('createTask.harness')"
                          :disabled="harnessLocked"
                          data-testid="task-harness-select"
                        />
                        <div
                          v-if="harnessLocked"
                          class="execution-environment__field-hint"
                          data-testid="task-harness-locked-hint"
                        >
                          {{ t('createTask.harnessLockedHint') }}
                        </div>
                        <div
                          v-if="harnessProviderMismatch"
                          class="execution-environment__field-hint"
                          data-testid="task-harness-provider-mismatch-hint"
                        >
                          {{ t('createTask.harnessProviderMismatchHint') }}
                        </div>
                      </label>
                    </div>
                    <div class="execution-environment__skills" data-testid="task-skill-selection">
                      <div class="execution-environment__skills-header">
                        <span>{{ t('createTask.skills') }}</span>
                        <label class="execution-environment__skills-inherit">
                          <span>{{ t('createTask.inheritProfileSkills') }}</span>
                          <n-switch
                            :value="inheritProfileSkills"
                            size="small"
                            :disabled="!taskSkillSelectionSupported"
                            @update:value="handleSkillInheritanceUpdate"
                          />
                        </label>
                      </div>
                      <n-select
                        :value="selectedSkillIds"
                        multiple
                        clearable
                        filterable
                        :disabled="inheritProfileSkills || !taskSkillSelectionSupported"
                        :options="taskSkillOptions"
                        :placeholder="t('createTask.selectSkills')"
                        :render-option="renderSkillOption"
                        :render-tag="renderSkillTag"
                        @update:value="handleSelectedSkillIdsUpdate"
                      />
                      <div
                        v-if="taskSkillSelectionNeedsAttention"
                        class="execution-environment__skills-snapshot-warning"
                        data-testid="task-skill-snapshot-warning"
                      >
                        <span v-if="changedTaskSkillSnapshots.length">
                          {{ t('createTask.skillSnapshotChangedHint') }}
                        </span>
                        <span v-if="profileDefaultSkillSelectionChanged">
                          {{ t('createTask.profileSkillSelectionChangedHint') }}
                        </span>
                        <div class="execution-environment__skills-snapshot-list">
                          <n-tag
                            v-for="snapshot in changedTaskSkillSnapshots"
                            :key="`${snapshot.version_id}-${snapshot.name}`"
                            size="small"
                            type="warning"
                            :bordered="false"
                          >
                            {{ snapshot.name }} · {{ t(
                              snapshot.unavailable
                                ? 'createTask.skillSnapshotUnavailable'
                                : 'createTask.skillSnapshotUpdated'
                            ) }}
                          </n-tag>
                        </div>
                        <n-button size="tiny" secondary @click="applyCurrentSkillSelection">
                          {{ t('createTask.applyCurrentSkillSelection') }}
                        </n-button>
                      </div>
                      <span class="execution-environment__skills-hint">
                        {{ !taskSkillSelectionSupported
                          ? t('createTask.skillsUnsupportedHint')
                          : inheritProfileSkills
                            ? t('createTask.profileSkillsHint')
                            : t('createTask.taskSkillsOverrideHint') }}
                      </span>
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
      </div>

      <template #footer>
        <div v-if="isFullFormVisible" class="task-form-drawer__footer">
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
import {
  ref, computed, watch, nextTick, onBeforeUnmount, onMounted, toRef, useAttrs, useId, h,
  type Component, type VNode,
} from 'vue'
import {
  NButton, NDrawer, NDrawerContent, NForm, NFormItem,
  NDatePicker, NInput, NSelect, NAlert, NTooltip, NSwitch, NSpin, NIcon, NScrollbar, NTag, useMessage,
  type SelectOption,
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  DocumentTextOutline,
  WarningOutline,
  CalendarOutline,
  ChatbubbleEllipsesOutline,
  CloseOutline,
  InformationCircleOutline,
  CodeSlashOutline,
  BulbOutline,
  CheckmarkCircleOutline,
  Checkmark,
  CopyOutline,
  FlashOutline,
  TimeOutline
} from '@vicons/ionicons5'
import VariableEditor from './VariableEditor.vue'
import HeatmapChart from './HeatmapChart.vue'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'
import {
  getRunInstructionTemplateDefaults,
  getTaskScheduleConstraints,
  type AIProvider,
  type Task, type TaskScheduleWindow, type TaskSkillSnapshot, type RunInstructionTemplateDefaults
} from '../api'
import { useBreakpoints } from '../composables/useBreakpoints'
import { formatDateTimeUtc8Compact, formatTimeUtc8, parseUtcDate } from '../utils/datetime'
import { buildScheduleTimeDisabled } from '../utils/scheduleWindow'
import { formatUsageResetAt } from '../utils/usageLimits'
import { issueDetailTooltipContentStyle, issueDetailTooltipThemeOverrides } from './issue-detail/tooltip'
import {
  createTaskModeDrafts,
  DEFAULT_REQUIRE_CHANGES,
  DEFAULT_TASK_PRIORITY,
  type TaskMode,
  type TaskModeDrafts,
} from '../features/tasks/taskFormModel'
import { useTaskScheduleContext } from '../features/tasks/useTaskScheduleContext'
import { usePromptTemplatePicker } from '../features/tasks/usePromptTemplatePicker'
import { useTaskExecutionOptions } from '../features/tasks/useTaskExecutionOptions'
import { useRunInstructionPreview } from '../features/tasks/useRunInstructionPreview'
import { useTaskSlotCapacity } from '../features/tasks/useTaskSlotCapacity'
import { useTaskFormSubmission } from '../features/tasks/useTaskFormSubmission'

function providerProtocol(provider: AIProvider): string | null {
  const protocol = provider.wire_protocol
  return typeof protocol === 'string' && protocol.trim() ? protocol.trim() : 'anthropic_messages'
}

function providerCompatibleWithHarness(
  provider: AIProvider,
  harnessKey: string | null | undefined,
): boolean {
  if (!harnessKey) return true
  // Harness/Endpoint compatibility is computed by the Backend
  // (harness_registry.compatible_harness_keys); the Frontend must not
  // reimplement the wire-protocol matrix.
  return (provider.compatible_harnesses ?? []).includes(harnessKey)
}

function renderProviderLabel(option: SelectOption) {
  const label = typeof option.label === 'string' ? option.label : String(option.value ?? '')
  const protocolText = typeof option.protocolText === 'string' ? option.protocolText : ''
  return h('div', { class: 'provider-option-label' }, [
    h('span', { class: 'provider-option-label__name' }, label),
    protocolText
      ? h('span', { class: 'provider-option-label__protocol' }, protocolText)
      : null,
  ])
}

defineOptions({ inheritAttrs: false })

const props = withDefaults(defineProps<{
  show: boolean
  mode?: 'create' | 'edit'
  issueId?: number
  issueDescription?: string
  hasClaudeSession?: boolean
  issueCurrentHarness?: string | null
  issueDefaultHarness?: string | null
  workerProfileId?: number | null
  defaultProviderId?: number | null
  task?: Task
}>(), {
  mode: 'create',
  hasClaudeSession: false,
  issueCurrentHarness: null,
  issueDefaultHarness: null
})

const emit = defineEmits<{
  'update:show': [value: boolean]
  created: [task: Task]
  updated: [task: Task]
}>()

const { t } = useI18n()
const { isMobile } = useBreakpoints()
const attrs = useAttrs()

// --- Skill selection: copy name + hover description (EEE-33) ---
const message = useMessage()
const copiedSkillValue = ref<number | string | null>(null)
let copiedSkillTimer: ReturnType<typeof setTimeout> | undefined

async function writeToClipboard(text: string): Promise<void> {
  // navigator.clipboard is only available in secure contexts (https/localhost);
  // on http (dev at http://192.168.50.129:8880) it is undefined, so fall back to
  // the synchronous execCommand path, which keeps the user-gesture context intact.
  if (navigator.clipboard && typeof navigator.clipboard.writeText === 'function') {
    try {
      await navigator.clipboard.writeText(text)
      return
    } catch {
      // API present but rejected (e.g. permission denied): fall through to execCommand
    }
  }
  if (typeof document.execCommand !== 'function') throw new Error('copy API unavailable')
  const textarea = document.createElement('textarea')
  textarea.value = text
  textarea.setAttribute('readonly', '')
  textarea.style.position = 'fixed'
  textarea.style.top = '-9999px'
  textarea.style.left = '-9999px'
  document.body.appendChild(textarea)
  const selection = document.getSelection()
  const previousRange = selection && selection.rangeCount > 0 ? selection.getRangeAt(0) : null
  textarea.select()
  let copied = false
  try {
    copied = document.execCommand('copy')
  } finally {
    textarea.remove()
    if (selection && previousRange) {
      selection.removeAllRanges()
      selection.addRange(previousRange)
    }
  }
  if (!copied) throw new Error('execCommand copy failed')
}

async function copySkillName(value: number | string, name: string) {
  try {
    await writeToClipboard(name)
    message.success(t('taskView.copied'))
    copiedSkillValue.value = value
    if (copiedSkillTimer) clearTimeout(copiedSkillTimer)
    copiedSkillTimer = setTimeout(() => {
      copiedSkillValue.value = null
    }, 2000)
  } catch {
    message.error(t('taskView.copyFailed'))
  }
}

function skillOptionName(option: SelectOption): string {
  const skillName = option.skillName
  if (typeof skillName === 'string' && skillName.trim()) return skillName
  return typeof option.label === 'string' ? option.label : String(option.value ?? '')
}

function skillOptionDescription(option: SelectOption): string {
  const description = option.description
  return typeof description === 'string' && description.trim() ? description : ''
}

function renderSkillOption({ node, option, selected }: { node: VNode; option: SelectOption; selected: boolean }) {
  const name = skillOptionName(option)
  const description = skillOptionDescription(option)
  const copied = copiedSkillValue.value === option.value
  const nodeClass = node.props?.class
  const pending = typeof nodeClass === 'string'
    && nodeClass.split(/\s+/).includes('n-base-select-option--pending')
  const tooltipProps = {
    trigger: 'hover' as const,
    placement: 'right' as const,
    disabled: !description,
    contentStyle: issueDetailTooltipContentStyle,
    themeOverrides: issueDetailTooltipThemeOverrides,
  }
  const forwardOptionClick = (event: MouseEvent) => {
    // naive-ui binds the option select handler onto `node`, which is shrink-wrapped
    // to the name. The `.skill-option` wrapper is the full-row click target; clicks
    // landing outside `node` (name-row whitespace, description row) are forwarded.
    // Skip clicks that already hit `node` to avoid a double toggle.
    const nodeElement = (node as VNode & { el?: Element }).el
    if (nodeElement?.contains(event.target as Node)) return
    ;(node.props as { onClick?: (e: MouseEvent) => void } | null | undefined)?.onClick?.(event)
  }
  const copyButton = h('button', {
    type: 'button',
    class: ['skill-option__copy', { 'skill-option__copy--copied': copied }],
    'aria-label': t('createTask.copySkillName'),
    tabindex: 0,
    onClick: (event: MouseEvent) => {
      event.stopPropagation()
      void copySkillName(option.value ?? '', name)
    },
    onMousedown: (event: MouseEvent) => event.stopPropagation(),
    onKeydown: (event: KeyboardEvent) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.stopPropagation()
        event.preventDefault()
        void copySkillName(option.value ?? '', name)
      }
    },
  }, [
    h(NIcon, { size: 14 }, { default: () => copied ? h(CheckmarkCircleOutline) : h(CopyOutline) }),
  ])
  return h('div', {
    class: ['skill-option', { 'skill-option--pending': pending }],
    onClick: forwardOptionClick,
  }, [
    h('div', { class: 'skill-option__name-row' }, [
      h(NTooltip, tooltipProps, {
        trigger: () => h('div', { class: 'skill-option__name' }, [node]),
        default: () => description,
      }),
      h('span', { class: 'skill-option__actions' }, [
        copyButton,
        selected ? h(NIcon, { class: 'skill-option__check', size: 16 }, { default: () => h(Checkmark) }) : null,
      ]),
    ]),
    description ? h(NTooltip, tooltipProps, {
      trigger: () => h('div', { class: 'skill-option__desc' }, description),
      default: () => description,
    }) : null,
  ])
}

function renderSkillTag({ option, handleClose }: { option: SelectOption; handleClose: () => void }) {
  const name = skillOptionName(option)
  const copied = copiedSkillValue.value === option.value
  return h(NTag, {
    size: 'small',
    closable: true,
    onClose: () => handleClose(),
  }, {
    default: () => [
      h('span', { class: 'skill-tag__name' }, name),
      h('button', {
        type: 'button',
        class: ['skill-tag__copy', { 'skill-tag__copy--copied': copied }],
        'aria-label': t('createTask.copySkillName'),
        tabindex: 0,
        onClick: (event: MouseEvent) => {
          event.stopPropagation()
          void copySkillName(option.value ?? '', name)
        },
        onMousedown: (event: MouseEvent) => event.stopPropagation(),
        onKeydown: (event: KeyboardEvent) => {
          if (event.key === 'Enter' || event.key === ' ') {
            event.stopPropagation()
            event.preventDefault()
            void copySkillName(option.value ?? '', name)
          }
        },
      }, [
        h(NIcon, { size: 14 }, { default: () => copied ? h(CheckmarkCircleOutline) : h(CopyOutline) }),
      ]),
    ],
  })
}

const showProxy = computed({
  get: () => props.show,
  set: (val) => emit('update:show', val)
})

const drawerTestId = computed(() => {
  const testId = attrs['data-testid']
  return typeof testId === 'string' ? testId : 'task-form-drawer'
})

// Form state
type DrawerView = 'mode-choice' | 'full-form'

interface TaskModeOption {
  mode: TaskMode
  label: string
  description: string
  summary: string
  icon: Component
}

const prompt = ref('')
const priority = ref(DEFAULT_TASK_PRIORITY)
const requireChanges = ref(DEFAULT_REQUIRE_CHANGES)
const taskMode = ref<TaskMode | null>(null)
const drawerView = ref<DrawerView>(props.mode === 'edit' ? 'full-form' : 'mode-choice')
const taskModeDetailTransitionEnabled = ref(true)
const modeChoicePanelRef = ref<HTMLElement | null>(null)
const fullFormPanelRef = ref<HTMLElement | null>(null)
const taskModeDrafts = ref<TaskModeDrafts>(createTaskModeDrafts())
let fullFormScrollTop = 0
const isModeChoiceVisible = computed(() => drawerView.value === 'mode-choice')
const isFullFormVisible = computed(() => drawerView.value === 'full-form')
const taskModeOptions = computed<TaskModeOption[]>(() => [
  {
    mode: 'freeform',
    label: t('issue.taskModeFreeform'),
    description: t('issue.taskModeFreeformDesc'),
    summary: t('issue.taskModeFreeformSummary'),
    icon: ChatbubbleEllipsesOutline,
  },
  {
    mode: 'execute',
    label: t('issue.taskModeExecute'),
    description: t('issue.taskModeExecuteDesc'),
    summary: t('issue.taskModeExecuteSummary'),
    icon: CodeSlashOutline,
  },
  {
    mode: 'plan',
    label: t('issue.taskModePlan'),
    description: t('issue.taskModePlanDesc'),
    summary: t('issue.taskModePlanSummary'),
    icon: BulbOutline,
  },
])
const currentTaskModeOption = computed(() =>
  taskModeOptions.value.find(option => option.mode === taskMode.value) ?? null
)
const startFreshSession = ref(false)
const taskModeErrorVisible = ref(false)
const runInstructionExpanded = ref(false)
const runInstructionAdvancedContentId = `${useId()}-run-instruction-advanced-content`
const executionEnvironmentExpanded = ref(false)
const executionEnvironmentContentId = `${useId()}-execution-environment-content`
const executionOptionsReady = ref(false)
const selectedProviderId = ref<number | null>(null)
const harnessKey = ref<string | null>(null)
const harnessLocked = computed(
  () => props.mode === 'edit'
    || (!startFreshSession.value && !!props.issueCurrentHarness),
)
const inheritProfileSkills = ref(true)
const selectedSkillIds = ref<number[]>([])
const skillSelectionDirty = ref(false)
const taskSkillSnapshots = ref<TaskSkillSnapshot[]>([])
const skillSnapshotResolutionApplied = ref(false)
const scheduleType = ref<'now' | 'scheduled'>('now')
const scheduledAt = ref<number | null>(null)
const scheduleWindow = ref<TaskScheduleWindow | null>(null)
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
  loadSkills,
  loadWorkerProfiles,
  selectableProviders,
  skillOptions,
  skills,
  skillsLoadSucceeded,
} = useTaskExecutionOptions({
  mode: toRef(props, 'mode'),
  task: toRef(props, 'task'),
  defaultProviderId: toRef(props, 'defaultProviderId'),
  workerProfileId: toRef(props, 'workerProfileId'),
  selectedProviderId,
})
const resolvedHarnessKey = computed(() =>
  harnessKey.value
  ?? props.issueCurrentHarness
  ?? props.issueDefaultHarness
  ?? effectiveWorkerProfile.value?.default_harness_key
  ?? 'claude',
)
const harnessCompatibleProviders = computed(() =>
  selectableProviders.value.filter(provider =>
    providerCompatibleWithHarness(provider, resolvedHarnessKey.value),
  ),
)
const providerOptions = computed(() =>
  harnessCompatibleProviders.value.map(provider => {
    const protocol = providerProtocol(provider)
    return {
      label: [
        `${provider.name} (${provider.model})`,
        provider.is_default ? ' ★' : '',
        provider.is_disabled ? ` - ${t('config.providers.disabled')}` : '',
      ].join(''),
      protocolText: protocol ?? '',
      value: provider.id,
      disabled: provider.is_disabled,
    }
  }),
)
const harnessProviderMismatch = computed(() =>
  selectableProviders.value.length > 0
  && !harnessCompatibleProviders.value.some(provider => !provider.is_disabled),
)
const executionEnvironmentMissing = computed(() =>
  executionOptionsReady.value
  && (
    !effectiveWorkerProfile.value
    || !effectiveProvider.value
    || harnessProviderMismatch.value
  )
)
const harnessOptions = computed(() => {
  const enabled = effectiveWorkerProfile.value?.enabled_harnesses
  if (!enabled || !enabled.length) return []
  return enabled.map(key => {
    const compatibleProviderAvailable = selectableProviders.value.length === 0
      || selectableProviders.value.some(
        provider => !provider.is_disabled && providerCompatibleWithHarness(provider, key),
      )
    return {
      label: key === 'codex' ? t('createTask.harnessCodex') : t('createTask.harnessClaude'),
      value: key,
      disabled: !harnessLocked.value && !compatibleProviderAvailable,
    }
  })
})
const executionEnvironmentOverridden = computed(() =>
  selectedProviderId.value !== null || !inheritProfileSkills.value
)
const providerAutoAdjusted = ref(false)
let providerAutoAdjustSource: number | null | undefined
let providerAutoAdjustedForHarness: string | null = null
function isSkillCapableWorkerKitVersion(value: string | null | undefined): boolean {
  const match = value?.trim().match(/^(\d+)\.(\d+)\.(\d+)$/)
  if (!match) return false
  const [major, minor, patch] = match.slice(1).map(Number)
  return major > 0 || minor > 3 || (minor === 3 && patch >= 5)
}
const taskSkillSelectionSupported = computed(() => {
  const profile = effectiveWorkerProfile.value
  const runtimeMode = props.mode === 'edit'
    ? props.task?.worker_runtime_mode
    : profile?.runtime_mode
  const workerKitVersion = props.mode === 'edit'
    ? props.task?.worker_kit_version
    : profile?.worker_kit_version
  if (runtimeMode !== 'mounted_kit') return false
  return isSkillCapableWorkerKitVersion(workerKitVersion)
})
const enabledProfileDefaultSkillIds = computed(() => {
  const enabledIds = new Set(skills.value.map(skill => skill.id))
  return (effectiveWorkerProfile.value?.default_skill_ids ?? []).filter(skillId =>
    enabledIds.has(skillId)
  )
})
const selectableProfileDefaultSkillIds = computed(() =>
  taskSkillSelectionSupported.value ? enabledProfileDefaultSkillIds.value : []
)
const taskSkillOptions = computed(() => {
  const options = [...skillOptions.value]
  const optionIds = new Set(options.map(option => option.value))
  for (const snapshot of taskSkillSnapshots.value) {
    if (typeof snapshot.id !== 'number' || optionIds.has(snapshot.id)) continue
    options.push({
      label: `${snapshot.name} (${t('createTask.skillSnapshotUnavailable')})`,
      value: snapshot.id,
      skillName: snapshot.name,
      description: '',
      disabled: true,
    })
    optionIds.add(snapshot.id)
  }
  return options
})
const changedTaskSkillSnapshots = computed(() => {
  if (
    props.mode !== 'edit'
    || !skillsLoadSucceeded.value
    || skillSnapshotResolutionApplied.value
  ) return []
  const currentById = new Map(skills.value.map(skill => [skill.id, skill]))
  return taskSkillSnapshots.value.flatMap(snapshot => {
    const current = typeof snapshot.id === 'number'
      ? currentById.get(snapshot.id)
      : undefined
    if (current && current.version_id === snapshot.version_id) return []
    return [{
      ...snapshot,
      unavailable: !current,
    }]
  })
})
const profileDefaultSkillSelectionChanged = computed(() => {
  if (
    props.mode !== 'edit'
    || (props.task?.skill_selection_source ?? 'profile') !== 'profile'
    || !skillsLoadSucceeded.value
    || !effectiveWorkerProfile.value
    || skillSnapshotResolutionApplied.value
  ) return false

  const currentDefaultIds = new Set(enabledProfileDefaultSkillIds.value)
  const snapshotIds = new Set(
    taskSkillSnapshots.value.flatMap(snapshot =>
      typeof snapshot.id === 'number' ? [snapshot.id] : []
    )
  )
  return currentDefaultIds.size !== snapshotIds.size
    || [...currentDefaultIds].some(skillId => !snapshotIds.has(skillId))
})
const taskSkillSelectionNeedsAttention = computed(() =>
  taskSkillSelectionSupported.value
  && (
    changedTaskSkillSnapshots.value.length > 0
    || profileDefaultSkillSelectionChanged.value
  )
)
const executionEnvironmentNeedsAttention = computed(() =>
  executionEnvironmentMissing.value || taskSkillSelectionNeedsAttention.value
)
const executionEnvironmentOpen = computed(() =>
  executionEnvironmentExpanded.value || executionEnvironmentNeedsAttention.value
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
    if (val !== 'freeform' && !runInstructionTemplate.value && runInstructionDefaults.value) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(val)
    }
  }
}, { flush: 'sync' })

watch([prompt, requireChanges], () => {
  invalidateRunInstructionPreview()
}, { flush: 'sync' })

watch(
  [effectiveWorkerProfile, skills],
  () => {
    if (props.mode === 'create' && !taskSkillSelectionSupported.value) {
      inheritProfileSkills.value = true
      selectedSkillIds.value = []
    } else if (props.mode === 'create' && inheritProfileSkills.value) {
      selectedSkillIds.value = [...selectableProfileDefaultSkillIds.value]
    }
  },
  { immediate: true },
)

watch(
  [startFreshSession, () => props.issueCurrentHarness],
  ([fresh, currentHarness]) => {
    if (!fresh && currentHarness) {
      harnessKey.value = currentHarness
    }
  },
)

function reconcileProviderForHarness(harnessKey: string, forceRestore = false) {
  const current = selectedProviderId.value !== null
    ? selectableProviders.value.find(provider => provider.id === selectedProviderId.value) ?? null
    : effectiveProvider.value
  if (!current || providerCompatibleWithHarness(current, harnessKey)) return

  if (forceRestore && providerAutoAdjustSource !== undefined) {
    const restoreValue = providerAutoAdjustSource
    providerAutoAdjustSource = undefined
    providerAutoAdjustedForHarness = null
    providerAutoAdjusted.value = false
    if (restoreValue === null) {
      selectedProviderId.value = null
      return
    }
    const restoreProvider = selectableProviders.value.find(provider => provider.id === restoreValue)
    if (restoreProvider && providerCompatibleWithHarness(restoreProvider, harnessKey)) {
      selectedProviderId.value = restoreValue
      return
    }
    selectedProviderId.value = null
    return
  }

  const fallback = harnessCompatibleProviders.value.find(provider => !provider.is_disabled)
  if (fallback) {
    if (providerAutoAdjustSource === undefined) {
      providerAutoAdjustSource = selectedProviderId.value
    }
    selectedProviderId.value = fallback.id
    providerAutoAdjustedForHarness = harnessKey
    providerAutoAdjusted.value = true
  } else {
    selectedProviderId.value = null
    providerAutoAdjustSource = undefined
    providerAutoAdjustedForHarness = null
    providerAutoAdjusted.value = false
  }
}

watch(resolvedHarnessKey, (harnessKey, previous) => {
  const shouldRestore = previous !== undefined
    && providerAutoAdjustSource !== undefined
    && providerAutoAdjustedForHarness === previous
  reconcileProviderForHarness(harnessKey, shouldRestore)
})

watch([selectableProviders, effectiveProvider], () => {
  reconcileProviderForHarness(resolvedHarnessKey.value)
})

watch([effectiveWorkerProfile, runInstructionDefaults], () => {
  refreshPristineTaskModeDrafts()
})

watch(() => props.show, (val) => {
  invalidateRunInstructionPreview()
  runInstructionExpanded.value = false
  executionEnvironmentExpanded.value = false
  if (val) {
    providerAutoAdjusted.value = false
    providerAutoAdjustSource = undefined
    providerAutoAdjustedForHarness = null
    if (props.mode === 'edit' && props.task) {
      drawerView.value = 'full-form'
      prompt.value = props.task.user_prompt ?? ''
      priority.value = props.task.priority ?? DEFAULT_TASK_PRIORITY
      requireChanges.value = props.task.require_changes ?? true
      taskMode.value = props.task.task_mode ?? 'execute'
      selectedProviderId.value = props.task.provider_id ?? null
      harnessKey.value = props.task.harness_key
        ?? effectiveWorkerProfile.value?.default_harness_key
        ?? 'claude'
      inheritProfileSkills.value =
        (props.task.skill_selection_source ?? 'profile') === 'profile'
      selectedSkillIds.value = [...(props.task.skill_ids ?? [])]
      taskSkillSnapshots.value = [...(props.task.skill_snapshots ?? [])]
      skillSelectionDirty.value = false
      skillSnapshotResolutionApplied.value = false
      const snapshot = taskMode.value === 'freeform'
        ? ''
        : props.task.run_instruction_template
          ?? getDefaultRunInstructionTemplate(taskMode.value)
          ?? ''
      runInstructionTemplate.value = snapshot
      initialRunInstructionTemplate.value = snapshot
      runInstructionDirty.value = false
      resetTaskModeDrafts()
      if (taskMode.value === 'execute') {
        taskModeDrafts.value.execute = {
          runInstructionTemplate: snapshot,
          runInstructionDirty: false,
          requireChanges: requireChanges.value,
        }
      } else if (taskMode.value === 'plan') {
        taskModeDrafts.value.plan = {
          runInstructionTemplate: snapshot,
          runInstructionDirty: false,
        }
      }
    } else if (props.mode === 'create') {
      drawerView.value = 'mode-choice'
      fullFormScrollTop = 0
      if (!prompt.value && props.issueDescription) {
        prompt.value = props.issueDescription
      }
      taskMode.value = null
      selectedProviderId.value = null
      inheritProfileSkills.value = true
      selectedSkillIds.value = [...selectableProfileDefaultSkillIds.value]
      taskSkillSnapshots.value = []
      skillSelectionDirty.value = false
      skillSnapshotResolutionApplied.value = false
      runInstructionTemplate.value = ''
      initialRunInstructionTemplate.value = ''
      runInstructionDirty.value = false
      requireChanges.value = DEFAULT_REQUIRE_CHANGES
      resetTaskModeDrafts()
      startFreshSession.value = false
      harnessKey.value = props.issueCurrentHarness
        ?? props.issueDefaultHarness
        ?? effectiveWorkerProfile.value?.default_harness_key
        ?? 'claude'
      scheduleType.value = 'now'
      scheduledAt.value = null
      scheduleWindow.value = null
      void loadScheduleContext()
      void loadCreateScheduleWindow()
    }
    usageLimitDetail.value = null
    taskModeErrorVisible.value = false
    if (props.mode === 'edit') void focusFullForm()
  } else if (props.mode === 'create') {
    drawerView.value = 'mode-choice'
  }
})

// --- Data loading ---
async function loadRunInstructionDefaults() {
  defaultsLoading.value = true
  defaultsError.value = ''
  try {
    runInstructionDefaults.value = await getRunInstructionTemplateDefaults()
    if (props.show && props.mode === 'edit' && props.task && !runInstructionTemplate.value) {
      const mode = props.task.task_mode ?? 'execute'
      if (mode !== 'freeform') {
        const snapshot = props.task.run_instruction_template ?? getDefaultRunInstructionTemplate(mode)
        runInstructionTemplate.value = snapshot
        initialRunInstructionTemplate.value = snapshot
      }
    }
    if (
      props.show
      && props.mode === 'create'
      && taskMode.value
      && taskMode.value !== 'freeform'
      && !runInstructionTemplate.value
    ) {
      runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
      initialRunInstructionTemplate.value = runInstructionTemplate.value
    }
    refreshPristineTaskModeDrafts()
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

function resetTaskModeDrafts() {
  taskModeDrafts.value = createTaskModeDrafts({
    executeTemplate: getDefaultRunInstructionTemplate('execute'),
    planTemplate: getDefaultRunInstructionTemplate('plan'),
    requireChanges: DEFAULT_REQUIRE_CHANGES,
  })
}

function refreshPristineTaskModeDrafts() {
  const executeDraft = taskModeDrafts.value.execute
  const planDraft = taskModeDrafts.value.plan
  const activeEditMode = props.mode === 'edit' && props.show ? taskMode.value : null
  if (!executeDraft.runInstructionDirty && activeEditMode !== 'execute') {
    executeDraft.runInstructionTemplate = getDefaultRunInstructionTemplate('execute')
  }
  if (!planDraft.runInstructionDirty && activeEditMode !== 'plan') {
    planDraft.runInstructionTemplate = getDefaultRunInstructionTemplate('plan')
  }
  if (activeEditMode) return
  if (taskMode.value === 'execute' && !runInstructionDirty.value) {
    runInstructionTemplate.value = executeDraft.runInstructionTemplate
  } else if (taskMode.value === 'plan' && !runInstructionDirty.value) {
    runInstructionTemplate.value = planDraft.runInstructionTemplate
  }
}

function saveCurrentTaskModeDraft() {
  if (taskMode.value === 'execute') {
    taskModeDrafts.value.execute = {
      runInstructionTemplate: runInstructionTemplate.value,
      runInstructionDirty: runInstructionDirty.value,
      requireChanges: requireChanges.value,
    }
  } else if (taskMode.value === 'plan') {
    taskModeDrafts.value.plan = {
      runInstructionTemplate: runInstructionTemplate.value,
      runInstructionDirty: runInstructionDirty.value,
    }
  }
}

function restoreTaskModeDraft(mode: TaskMode) {
  if (mode === 'freeform') {
    requireChanges.value = false
    runInstructionTemplate.value = ''
    runInstructionDirty.value = false
    return
  }
  if (mode === 'execute') {
    const draft = taskModeDrafts.value.execute
    runInstructionTemplate.value = draft.runInstructionTemplate
      || getDefaultRunInstructionTemplate(mode)
    runInstructionDirty.value = draft.runInstructionDirty
    requireChanges.value = draft.requireChanges
    return
  }
  const draft = taskModeDrafts.value.plan
  runInstructionTemplate.value = draft.runInstructionTemplate
    || getDefaultRunInstructionTemplate(mode)
  runInstructionDirty.value = draft.runInstructionDirty
  requireChanges.value = false
}

function fullFormScrollContainer(): HTMLElement | null {
  if (!fullFormPanelRef.value) return null
  return fullFormPanelRef.value.closest<HTMLElement>('.n-drawer-body-content-wrapper')
    ?? fullFormPanelRef.value
}

function focusWithoutScroll(element: HTMLElement | null) {
  if (!element) return
  element.focus({ preventScroll: true })
}

async function focusFullForm() {
  await nextTick()
  const scrollContainer = fullFormScrollContainer()
  const promptEditor = fullFormPanelRef.value?.querySelector<HTMLElement>(
    '.prompt-form-section textarea:not([disabled]), .prompt-form-section [contenteditable="true"]'
  ) ?? null
  const firstEditable = promptEditor ?? fullFormPanelRef.value?.querySelector<HTMLElement>(
    'textarea:not([disabled]), input:not([disabled]), button:not([disabled]), [tabindex="0"]'
  ) ?? null
  focusWithoutScroll(firstEditable)
  if (scrollContainer) scrollContainer.scrollTop = fullFormScrollTop
}

async function selectTaskMode(mode: TaskMode) {
  taskModeDetailTransitionEnabled.value = false
  saveCurrentTaskModeDraft()
  taskMode.value = mode
  restoreTaskModeDraft(mode)
  runInstructionExpanded.value = false
  drawerView.value = 'full-form'
  await nextTick()
  taskModeDetailTransitionEnabled.value = true
  await focusFullForm()
}

async function changeTaskMode() {
  saveCurrentTaskModeDraft()
  fullFormScrollTop = fullFormScrollContainer()?.scrollTop ?? 0
  drawerView.value = 'mode-choice'
  await nextTick()
  const selector = taskMode.value
    ? `[data-task-mode="${taskMode.value}"]`
    : '[data-task-mode]'
  focusWithoutScroll(modeChoicePanelRef.value?.querySelector<HTMLElement>(selector) ?? null)
}

function handleRunInstructionInput(value: string) {
  runInstructionTemplate.value = value
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function restoreRunInstructionDefault() {
  if (!taskMode.value || taskMode.value === 'freeform') return
  runInstructionTemplate.value = getDefaultRunInstructionTemplate(taskMode.value)
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}

function getDefaultRunInstructionTemplate(mode: Exclude<TaskMode, 'freeform'>): string {
  const profile = effectiveWorkerProfile.value
  if (profile) {
    const profileTemplate = mode === 'plan'
      ? profile.default_plan_run_instruction_template
      : profile.default_execute_run_instruction_template
    if (profileTemplate) return profileTemplate
  }
  return runInstructionDefaults.value?.[mode].content ?? ''
}

function toggleExecutionEnvironment() {
  if (executionEnvironmentNeedsAttention.value) {
    executionEnvironmentExpanded.value = true
    return
  }
  executionEnvironmentExpanded.value = !executionEnvironmentExpanded.value
}

function restoreExecutionEnvironmentDefaults() {
  selectedProviderId.value = null
  providerAutoAdjusted.value = false
  providerAutoAdjustSource = undefined
  providerAutoAdjustedForHarness = null
  handleSkillInheritanceUpdate(true)
  if (!executionEnvironmentMissing.value) {
    executionEnvironmentExpanded.value = false
  }
}

function handleProviderChange(value: number | null) {
  selectedProviderId.value = value
  providerAutoAdjusted.value = false
  providerAutoAdjustSource = undefined
  providerAutoAdjustedForHarness = null
}

function handleSkillInheritanceUpdate(value: boolean) {
  if (props.mode === 'edit' && inheritProfileSkills.value !== value) {
    skillSelectionDirty.value = true
    skillSnapshotResolutionApplied.value = true
  }
  inheritProfileSkills.value = value
  if (value) {
    selectedSkillIds.value = [...selectableProfileDefaultSkillIds.value]
  }
}

function handleSelectedSkillIdsUpdate(value: number[]) {
  selectedSkillIds.value = [...value]
  if (props.mode === 'edit') {
    skillSelectionDirty.value = true
    skillSnapshotResolutionApplied.value = true
  }
}

function applyCurrentSkillSelection() {
  executionEnvironmentExpanded.value = true
  skillSelectionDirty.value = true
  skillSnapshotResolutionApplied.value = true
  if (inheritProfileSkills.value) {
    selectedSkillIds.value = [...selectableProfileDefaultSkillIds.value]
    return
  }
  const enabledIds = new Set(skills.value.map(skill => skill.id))
  selectedSkillIds.value = taskSkillSnapshots.value.flatMap(snapshot =>
    typeof snapshot.id === 'number' && enabledIds.has(snapshot.id)
      ? [snapshot.id]
      : []
  )
}

async function loadExecutionOptions() {
  executionOptionsReady.value = false
  await Promise.all([loadProviders(), loadWorkerProfiles(), loadSkills()])
  executionOptionsReady.value = true
}

function isScheduleDateDisabled(timestamp: number): boolean {
  const candidate = new Date(timestamp)
  const today = new Date()
  candidate.setHours(0, 0, 0, 0)
  today.setHours(0, 0, 0, 0)
  if (candidate.getTime() < today.getTime()) return true
  const window = scheduleWindow.value
  if (!window) return false
  if (window.has_valid_window === false) return true
  const dayStart = new Date(timestamp)
  dayStart.setHours(0, 0, 0, 0)
  const dayEnd = dayStart.getTime() + 24 * 60 * 60 * 1000 - 1
  if (window.min_scheduled_at) {
    const min = parseUtcDate(window.min_scheduled_at).getTime()
    if (dayEnd < min) return true
  }
  if (window.max_scheduled_at) {
    const max = parseUtcDate(window.max_scheduled_at).getTime()
    if (dayStart.getTime() > max) return true
  }
  return false
}

const isTimeDisabled = computed(() => buildScheduleTimeDisabled(scheduleWindow.value))

async function loadCreateScheduleWindow() {
  scheduleWindow.value = null
  if (props.mode !== 'create' || !props.issueId) return
  try {
    scheduleWindow.value = await getTaskScheduleConstraints({ issue_id: props.issueId })
  } catch {
    scheduleWindow.value = null
  }
}

const createScheduleConstraintHint = computed(() => {
  const window = scheduleWindow.value
  if (!window || window.has_valid_window === false) {
    return window?.has_valid_window === false
      ? t('scheduleConflict.noValidWindow')
      : null
  }
  if (window.min_scheduled_at && window.min_source_task_id != null) {
    return t('createTask.scheduleFloorNotBefore', { source: window.min_source_task_id })
  }
  return null
})

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
  harnessKey,
  scheduleType,
  scheduledAt,
  runInstructionTemplate,
  initialRunInstructionTemplate,
  runInstructionDirty,
  inheritProfileSkills,
  selectedSkillIds,
  skillSelectionDirty,
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

onBeforeUnmount(() => {
  if (copiedSkillTimer) clearTimeout(copiedSkillTimer)
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

.task-mode-choice,
.task-full-form {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  overflow-x: clip;
}

.task-mode-choice__header {
  margin-bottom: 18px;
}

.task-mode-choice__title {
  margin: 0;
  color: var(--n-text-color);
  font-size: 20px;
  font-weight: 650;
  line-height: 28px;
}

.task-mode-choice__hint {
  margin: 5px 0 0;
  color: var(--n-text-color-3);
  font-size: 13px;
  line-height: 20px;
}

.task-mode-choice__list {
  display: grid;
  gap: 10px;
  width: 100%;
}

.task-mode-choice__option {
  display: grid;
  grid-template-columns: 40px minmax(0, 1fr) 20px;
  align-items: center;
  gap: 12px;
  width: 100%;
  min-width: 0;
  min-height: 78px;
  padding: 14px 16px;
  border: 1px solid var(--n-border-color);
  border-radius: 10px;
  color: inherit;
  background: rgba(128, 128, 128, 0.025);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition:
    border-color 0.15s ease,
    background-color 0.15s ease,
    box-shadow 0.15s ease,
    transform 0.15s ease;
}

.task-mode-choice__option:hover,
.task-mode-choice__option--active {
  border-color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.06);
}

.task-mode-choice__option:focus-visible {
  outline: 2px solid var(--n-primary-color);
  outline-offset: 2px;
  box-shadow: 0 0 0 3px rgba(99, 226, 183, 0.14);
}

.task-mode-choice__icon {
  display: grid;
  width: 40px;
  height: 40px;
  place-items: center;
  border-radius: 9px;
  color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.1);
}

.task-mode-choice__copy {
  display: grid;
  min-width: 0;
  gap: 3px;
}

.task-mode-choice__label {
  color: var(--n-text-color);
  font-size: 14px;
  font-weight: 650;
  line-height: 20px;
}

.task-mode-choice__description {
  min-width: 0;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 18px;
  overflow-wrap: anywhere;
}

.task-mode-choice__check {
  color: var(--n-primary-color);
}

.task-mode-summary {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  min-height: 52px;
  margin-bottom: 20px;
  padding: 8px 10px 8px 12px;
  border: 1px solid rgba(128, 128, 128, 0.24);
  border-radius: 9px;
  background: rgba(128, 128, 128, 0.035);
}

.task-mode-summary__icon {
  display: grid;
  flex: 0 0 32px;
  width: 32px;
  height: 32px;
  place-items: center;
  border-radius: 8px;
  color: var(--n-primary-color);
  background: rgba(99, 226, 183, 0.1);
}

.task-mode-summary__copy {
  display: flex;
  min-width: 0;
  flex: 1;
  align-items: baseline;
  gap: 6px;
}

.task-mode-summary__label {
  flex-shrink: 0;
  color: var(--n-text-color);
  font-size: 13px;
  font-weight: 650;
}

.task-mode-summary__separator,
.task-mode-summary__description {
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 18px;
}

.task-mode-summary__description {
  min-width: 0;
  overflow-wrap: anywhere;
}

.task-mode-summary__change {
  min-width: 44px;
  min-height: 44px;
  flex-shrink: 0;
}

.task-form-view--active {
  animation: task-form-view-enter 0.15s ease-out both;
}

@keyframes task-form-view-enter {
  from {
    opacity: 0;
  }

  to {
    opacity: 1;
  }
}

.task-form-drawer__footer {
  display: flex;
  justify-content: flex-end;
  padding-bottom: max(0px, env(safe-area-inset-bottom));
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
  margin-bottom: 16px;
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
  .task-mode-choice__option,
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

  .task-form-view--active {
    animation: none;
  }
}

:deep(.n-form-item-blank) {
  flex-direction: column;
  align-items: flex-start;
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

.require-changes-row {
  display: flex;
  align-items: center;
  gap: 6px;
  padding-left: 12px;
}

.task-mode-detail-reveal {
  display: grid;
  grid-template-rows: 1fr;
  margin-top: 0;
  margin-bottom: 16px;
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
    margin-bottom 0.18s cubic-bezier(0.4, 0, 0.2, 1),
    opacity 0.14s ease,
    transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-mode-detail-enter-from,
.task-mode-detail-leave-to {
  grid-template-rows: 0fr;
  margin-bottom: 0;
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

.schedule-detail-panel__constraint {
  margin: 8px 0 0;
  padding: 8px 10px;
  border-radius: 8px;
  background: rgba(32, 128, 240, 0.06);
  color: rgba(29, 78, 216, 0.9);
  font-size: 12px;
  line-height: 1.45;
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
  align-items: start;
}

.execution-environment__field {
  display: grid;
  gap: 5px;
  min-width: 0;
  align-content: start;
}

.execution-environment__field :deep(.n-input),
.execution-environment__field :deep(.n-select) {
  height: 34px;
}

.execution-environment__field :deep(.n-base-selection) {
  min-height: 34px;
}

.execution-environment__field > span {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.execution-environment__field-hint {
  color: var(--n-text-color-3);
  font-size: 10px;
  line-height: 14px;
}

.execution-environment__skills {
  display: grid;
  gap: 6px;
  margin-top: 10px;
}

.execution-environment__skills-header,
.execution-environment__skills-inherit {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.execution-environment__skills-header > span,
.execution-environment__skills-inherit,
.execution-environment__skills-hint {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.execution-environment__skills-snapshot-warning {
  display: grid;
  gap: 6px;
  padding: 8px;
  color: var(--n-warning-color);
  font-size: 11px;
  line-height: 16px;
  background: color-mix(in srgb, var(--n-warning-color) 8%, transparent);
  border: 1px solid color-mix(in srgb, var(--n-warning-color) 28%, transparent);
  border-radius: 6px;
}

.execution-environment__skills-snapshot-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
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
  .task-mode-choice__option {
    grid-template-columns: 36px minmax(0, 1fr) 18px;
    gap: 10px;
    min-height: 88px;
    padding: 12px;
  }

  .task-mode-choice__icon {
    width: 36px;
    height: 36px;
  }

  .task-mode-summary {
    align-items: flex-start;
    flex-wrap: wrap;
  }

  .task-mode-summary__copy {
    flex-basis: calc(100% - 98px);
    flex-wrap: wrap;
  }

  .task-mode-summary__change {
    margin-left: auto;
  }

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

<style>
.provider-option-label {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
  max-width: 100%;
  padding: 2px 0;
  line-height: 1.35;
}

.provider-option-label__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.88);
}

.provider-option-label__protocol {
  align-self: flex-start;
  max-width: 100%;
  padding: 1px 7px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  border-radius: 999px;
  background: rgba(15, 23, 42, 0.07);
  color: rgba(15, 23, 42, 0.6);
  font-size: 11px;
  line-height: 1.5;
}

.task-provider-select .n-base-selection-input__content .provider-option-label {
  display: block;
  padding: 0;
  line-height: 1.5;
}

.task-provider-select .n-base-selection-input__content .provider-option-label__name {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-provider-select .n-base-selection-input__content .provider-option-label__protocol {
  display: none;
}

.task-provider-select-menu .n-base-select-option {
  min-height: 50px;
  padding-top: 6px;
  padding-bottom: 6px;
}

/* Skill option / tag copy + hover description (render-function content, unscoped) */
.skill-option {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  box-sizing: border-box;
  width: 100%;
  min-width: 0;
  min-height: var(--n-option-height, 36px);
  padding: 6px 12px;
  position: relative;
  border-radius: var(--n-border-radius, 3px);
  cursor: pointer;
}

/* Full-row hover highlight — the naive-ui node is shrink-wrapped to the name, so
   the hover state must live on the wrapper to keep the whole row hittable. */
.skill-option:hover,
.skill-option:focus-within,
.skill-option--pending {
  background-color: var(--n-option-color-pending, rgba(0, 0, 0, 0.05));
}

.skill-option__name-row {
  display: flex;
  align-items: center;
  gap: 6px;
  width: 100%;
  min-width: 0;
}

.skill-option__name {
  display: flex;
  flex: 1 1 auto;
  align-items: center;
  max-width: 100%;
  min-width: 0;
}

/* Shrink the naive-ui option node to its label so the copy button sits next to
   the name. `padding: 0` drops the reserved checkmark slot so the node does not
   widen on select; the naive-ui checkmark itself is hidden (see below) in favor
   of our own `.skill-option__check` rendered as a flex sibling. */
.skill-option__name .n-base-select-option {
  display: inline-flex;
  width: auto;
  max-width: 100%;
  min-width: 0;
  min-height: auto;
  padding: 0;
}

/* The selected node paints its own inset background via `::before`. The wrapper
   owns hover/focus feedback so the highlight stays aligned to the whole row. */
.skill-option__name .n-base-select-option::before {
  display: none;
}

/* Hide the naive-ui checkmark (absolute, right-aligned) — the selected state is
   shown by our own `.skill-option__check`, which is a normal flex item so it can
   never be painted over by the node's selected background. */
.skill-option__name .n-base-select-option__check {
  display: none;
}

.skill-option__actions {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  margin-left: auto;
}

/* Selected-state checkmark stays in a distinct trailing slot after copy feedback. */
.skill-option__check {
  flex: 0 0 auto;
  color: var(--n-option-check-color, #18a058);
}

.skill-option__desc {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.4;
  width: 100%;
}

.skill-option__copy,
.skill-tag__copy {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  box-sizing: border-box;
  width: 22px;
  height: 22px;
  padding: 0;
  border: 0;
  border-radius: 4px;
  background: transparent;
  color: var(--n-text-color-3, #8a8f98);
  cursor: pointer;
  transition: color 0.15s ease, background-color 0.15s ease;
}

.skill-option__copy:hover,
.skill-tag__copy:hover {
  color: var(--n-primary-color, #18a058);
  background: rgba(128, 128, 128, 0.12);
}

.skill-option__copy:focus-visible,
.skill-tag__copy:focus-visible {
  outline: 2px solid var(--n-primary-color, #18a058);
  outline-offset: 1px;
}

.skill-option__copy--copied,
.skill-tag__copy--copied {
  color: var(--n-primary-color, #18a058);
  background: rgba(24, 160, 88, 0.1);
}

.skill-option__copy--copied:hover,
.skill-tag__copy--copied:hover {
  background: rgba(24, 160, 88, 0.16);
}

.execution-environment__skills .n-tag__content {
  display: inline-flex;
  align-items: center;
  height: 100%;
}

.skill-tag__name {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

</style>
