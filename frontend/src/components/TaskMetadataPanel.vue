<template>
  <n-card class="task-metadata-panel" :bordered="false">
    <template #header>
      <div class="panel-header">
        <div>
          <div class="panel-eyebrow">{{ t('taskView.executionContext') }}</div>
          <div class="panel-title">{{ t('taskView.taskOverview') }}</div>
        </div>
        <div class="panel-badges">
          <n-tag type="default" size="small" :bordered="false">{{ formatPriority(task.priority) }}</n-tag>
        </div>
      </div>
    </template>

    <div class="metadata-body">
      <!-- Project -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><FolderOpenOutline /></n-icon>
          {{ t('common.project') }}
        </span>
        <span class="metadata-value">
          <a
            v-if="task.project_url"
            :href="task.project_url"
            target="_blank"
            rel="noopener noreferrer"
            class="app-link metadata-reference-link project-reference-link"
          >
            <span class="metadata-reference-link__title">{{ projectDisplayName }}</span>
          </a>
          <span v-else>{{ projectDisplayName }}</span>
        </span>
      </div>

      <!-- Source -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon">
            <GitMergeOutline v-if="task.issue" />
            <PersonOutline v-else />
          </n-icon>
          {{ t('common.source') }}
        </span>
        <span class="metadata-value">
          <template v-if="task.issue">
            <router-link
              :to="`/issues/${task.issue.id}`"
              class="app-link metadata-reference-link task-issue-link"
            >
              <span class="task-issue-link__id">#{{ task.issue.id }}</span>
              <span class="metadata-reference-link__title task-issue-link__title">
                {{ task.issue.title }}
              </span>
            </router-link>
            <n-tag v-if="triggerSourceMeta" size="small" round :type="triggerSourceMeta.type" class="trigger-source-tag">
              {{ triggerSourceMeta.label }}
            </n-tag>
          </template>
          <template v-else>
            <span class="metadata-manual">{{ t('taskView.manualCreation') }}</span>
            <n-tag v-if="triggerSourceMeta" size="small" round :type="triggerSourceMeta.type" class="trigger-source-tag">
              {{ triggerSourceMeta.label }}
            </n-tag>
          </template>
        </span>
      </div>

      <!-- Initiator -->
      <div v-if="task.initiator_username" class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><PersonOutline /></n-icon>
          {{ t('common.initiator') }}
        </span>
        <span class="metadata-value">{{ task.initiator_username }}</span>
      </div>

      <!-- Retry Source -->
      <div v-if="task.is_retry && task.retry_source_task_id" class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><RefreshOutline /></n-icon>
          {{ t('taskView.retryOf') }}
        </span>
        <span class="metadata-value">
          <router-link :to="`/tasks/${task.retry_source_task_id}`" class="app-link">
            Task #{{ task.retry_source_task_id }}
          </router-link>
        </span>
      </div>

      <TaskRuntimeSummaryRows :task="task" />

      <!-- Harness engine -->
      <div v-if="task.harness_key" class="metadata-row" data-testid="task-harness-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><CubeOutline /></n-icon>
          {{ t('taskView.harness') }}
        </span>
        <span class="metadata-value">
          <span
            class="task-mode-chip"
            :class="{ 'task-mode-chip--codex': task.harness_key === 'codex' }"
          >
            <n-icon size="15" class="task-mode-chip__icon"><CubeOutline /></n-icon>
            <span>{{ harnessMeta }}</span>
          </span>
        </span>
      </div>

      <!-- Task mode -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon :component="taskModeMeta.icon" size="14" class="metadata-label-icon" />
          {{ t('taskView.taskMode') }}
        </span>
        <span class="metadata-value">
          <span class="task-mode-chip" :class="taskModeMeta.modifierClass">
            <n-icon :component="taskModeMeta.icon" size="15" class="task-mode-chip__icon" />
            <span>{{ taskModeMeta.label }}</span>
          </span>
        </span>
      </div>

      <!-- Session mode -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><ChatbubbleEllipsesOutline /></n-icon>
          {{ t('taskView.sessionMode') }}
        </span>
        <span class="metadata-value">
          <n-tag size="small" :bordered="false">{{ sessionModeText }}</n-tag>
        </span>
      </div>

      <!-- Branch flow -->
      <div class="metadata-row">
        <span class="metadata-label metadata-label--top">
          <n-icon size="14" class="metadata-label-icon"><GitBranchOutline /></n-icon>
          {{ t('taskView.branchFlow') }}
        </span>
        <span class="metadata-value">
          <span
            class="branch-flow"
            :class="{ 'branch-flow--direct-only': !task.issue?.base_branch && !task.issue?.branch_name && !task.issue?.target_branch }"
          >
            <span v-if="task.issue?.base_branch" class="branch-flow__stage">
              <span class="branch-flow__marker branch-flow__marker--base" aria-hidden="true"></span>
              <span class="branch-flow__content">
                <span class="branch-flow__label">{{ t('taskView.branchBase') }}</span>
                <a v-if="branchUrl(task.issue.base_branch)" :href="branchUrl(task.issue.base_branch)!" target="_blank" rel="noopener noreferrer" class="branch-flow__name app-link">{{ task.issue.base_branch }}</a>
                <span v-else class="branch-flow__name">{{ task.issue.base_branch }}</span>
              </span>
            </span>
            <span v-if="!task.issue?.branch_name" class="branch-flow__mode">{{ t('taskView.directPush') }}</span>
            <span v-if="task.issue?.branch_name" class="branch-flow__stage">
              <span class="branch-flow__marker branch-flow__marker--work" aria-hidden="true"></span>
              <span class="branch-flow__content">
                <span class="branch-flow__label">{{ t('taskView.branchWork') }}</span>
                <a v-if="branchUrl(task.issue.branch_name)" :href="branchUrl(task.issue.branch_name)!" target="_blank" rel="noopener noreferrer" class="branch-flow__name app-link">{{ task.issue.branch_name }}</a>
                <span v-else class="branch-flow__name">{{ task.issue.branch_name }}</span>
              </span>
            </span>
            <span v-if="task.issue?.target_branch" class="branch-flow__stage">
              <span class="branch-flow__marker branch-flow__marker--target" aria-hidden="true"></span>
              <span class="branch-flow__content">
                <span class="branch-flow__label">{{ t('taskView.branchTarget') }}</span>
                <a v-if="branchUrl(task.issue.target_branch)" :href="branchUrl(task.issue.target_branch)!" target="_blank" rel="noopener noreferrer" class="branch-flow__name app-link">{{ task.issue.target_branch }}</a>
                <span v-else class="branch-flow__name">{{ task.issue.target_branch }}</span>
              </span>
            </span>
          </span>
        </span>
      </div>

      <!-- Merge Request -->
      <div class="metadata-row">
        <span class="metadata-label">
          <n-icon size="14" class="metadata-label-icon"><GitPullRequest /></n-icon>
          {{ t('taskView.mergeRequest') }}
        </span>
        <span class="metadata-value">
          <template v-if="task.issue?.merge_request_url">
            <a :href="task.issue.merge_request_url" target="_blank" rel="noopener noreferrer" class="app-link mr-link">
              {{ task.issue.merge_request_iid ? `!${task.issue.merge_request_iid}` : t('taskView.mergeRequest') }}
            </a>
          </template>
          <template v-else-if="task.issue?.target_branch">
            <span class="mr-pending">{{ t('taskView.mrWillBeCreated') }} → <span class="mr-target-branch">{{ task.issue.target_branch }}</span></span>
          </template>
          <template v-else>
            <span class="mr-none">{{ t('taskView.mrNotCreated') }}</span>
          </template>
        </span>
      </div>

      <!-- Time axis -->
      <div class="metadata-row">
        <span class="metadata-label metadata-label--top">
          <n-icon size="14" class="metadata-label-icon"><TimeOutline /></n-icon>
          {{ t('common.timeline') }}
        </span>
        <div class="time-axis" :class="{ 'time-axis--single': !hasAdditionalTimelinePoint }">
          <div class="time-point">
            <span class="time-point__marker" aria-hidden="true"></span>
            <span class="time-point__content">
              <span class="time-point__label">{{ t('common.created') }}</span>
              <time class="time-point__value" :datetime="task.created_at">{{ formatDate(task.created_at) }}</time>
            </span>
          </div>
          <div v-if="task.scheduled_at && isSignificantSchedule(task.scheduled_at, task.created_at)" class="time-point">
            <span class="time-point__marker time-point__marker--scheduled" aria-hidden="true"></span>
            <span class="time-point__content">
              <span class="time-point__label">{{ t('common.scheduledAt') }}</span>
              <time class="time-point__value" :datetime="task.scheduled_at">{{ formatDate(task.scheduled_at) }}</time>
            </span>
          </div>
          <div v-if="task.started_at" class="time-point">
            <span class="time-point__marker time-point__marker--active" aria-hidden="true"></span>
            <span class="time-point__content">
              <span class="time-point__label">{{ t('common.started') }}</span>
              <time class="time-point__value" :datetime="task.started_at">{{ formatDate(task.started_at) }}</time>
            </span>
          </div>
          <div v-if="task.completed_at" class="time-point">
            <span class="time-point__marker time-point__marker--complete" aria-hidden="true"></span>
            <span class="time-point__content">
              <span class="time-point__label">{{ t('taskView.completedAt') }}</span>
              <time class="time-point__value" :datetime="task.completed_at">{{ formatDate(task.completed_at) }}</time>
            </span>
          </div>
        </div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NCard, NIcon, NTag } from 'naive-ui'
import {
  FolderOpenOutline,
  GitMergeOutline,
  PersonOutline,
  GitBranchOutline,
  TimeOutline,
  GitPullRequest,
  RefreshOutline,
  ChatbubbleEllipsesOutline,
  CodeSlashOutline,
  BulbOutline,
  InformationCircleOutline,
  CubeOutline
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task } from '../api'
import TaskRuntimeSummaryRows from './TaskRuntimeSummaryRows.vue'
import { formatPriority } from '../utils/format'
import { formatDateTimeUtc8 } from '../utils/datetime'
import { getTaskModePresentation } from '../features/tasks/taskModePresentation'

const props = defineProps<{
  task: Task
}>()

const { t } = useI18n()

const projectDisplayName = computed(() => {
  return props.task.project_path_with_namespace
    || props.task.project_name
    || `Project #${props.task.project_id}`
})

function branchUrl(branchName: string): string | null {
  if (!props.task.project_url || !branchName) return null
  return `${props.task.project_url}/-/tree/${encodeURIComponent(branchName)}`
}

function formatDate(dateStr: string): string {
  return formatDateTimeUtc8(dateStr)
}

const taskModeMeta = computed(() => {
  const presentation = getTaskModePresentation(props.task.task_mode)
  const iconMap = {
    implementation: CodeSlashOutline,
    freeform: ChatbubbleEllipsesOutline,
    analysis: BulbOutline,
    unknown: InformationCircleOutline,
  }

  return {
    icon: iconMap[presentation.icon],
    label: t(presentation.i18nKey),
    modifierClass: `task-mode-chip--${presentation.modifier}`,
  }
})

const harnessMeta = computed(() => {
  const key = props.task.harness_key
  if (key === 'codex') return t('taskView.harnessCodex')
  if (key === 'claude') return t('taskView.harnessClaude')
  if (key === 'pi') return t('taskView.harnessPi')
  if (key === 'opencode') return t('taskView.harnessOpenCode')
  return key || t('common.notAvailable')
})

const sessionModeText = computed(() =>
  props.task.session_mode === 'fresh'
    ? t('taskView.sessionModeFresh')
    : t('taskView.sessionModeContinue')
)

const triggerSourceMeta = computed(() => {
  const source = props.task.trigger_source || 'manual'
  if (source === 'manual') return null

  const typeMap: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
    retry: 'warning',
    follow_up: 'info',
    ci_auto_repair: 'error'
  }

  return {
    type: typeMap[source] ?? 'default',
    label: t(`taskView.triggerSource.${source}`)
  }
})

const hasAdditionalTimelinePoint = computed(() =>
  !!props.task.started_at
  || !!props.task.completed_at
  || (
    !!props.task.scheduled_at
    && isSignificantSchedule(props.task.scheduled_at, props.task.created_at)
  )
)

function isSignificantSchedule(scheduledAt: string, createdAt: string): boolean {
  try {
    const diff = Math.abs(new Date(scheduledAt).getTime() - new Date(createdAt).getTime())
    return diff > 60 * 1000 // more than 60 seconds difference
  } catch {
    return false
  }
}
</script>

<style scoped>
.task-metadata-panel {
  border-radius: var(--app-card-radius);
  height: 100%;
}

.panel-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.panel-eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0;
  text-transform: uppercase;
}

.panel-title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
}

.panel-badges {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.metadata-body {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 10px;
  row-gap: 12px;
  align-items: center;
}

.metadata-row {
  display: contents;
}

.metadata-label {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  white-space: nowrap;
}

.metadata-label--top {
  align-self: start;
  padding-top: 3px;
}

.metadata-row > :last-child {
  min-width: 0;
}

.metadata-value {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  min-width: 0;
  font-size: 14px;
  color: var(--n-text-color-1);
  word-break: break-word;
  overflow-wrap: anywhere;
}

.trigger-source-tag {
  margin-left: 0;
  vertical-align: middle;
}

.metadata-manual {
  color: var(--n-text-color-2, #666);
}

.task-mode-chip {
  --task-mode-chip-accent: var(--n-text-color-3, #8a8f98);

  display: inline-flex;
  align-items: center;
  gap: 5px;
  max-width: 100%;
  padding: 3px 9px;
  border: 1px solid rgba(128, 128, 128, 0.14);
  border-radius: 999px;
  background: rgba(128, 128, 128, 0.07);
  color: var(--n-text-color-2, #666);
  font-size: 13px;
  font-weight: 500;
  line-height: 1.35;
  vertical-align: middle;
}

.task-mode-chip__icon {
  flex: 0 0 auto;
  color: var(--task-mode-chip-accent);
}

.task-mode-chip--execute {
  --task-mode-chip-accent: #64748b;
}

.task-mode-chip--freeform {
  --task-mode-chip-accent: var(--n-primary-color, #18a058);
}

.task-mode-chip--plan {
  --task-mode-chip-accent: #78716c;
}

.task-mode-chip--unknown {
  --task-mode-chip-accent: var(--n-text-color-3, #8a8f98);
}

.task-mode-chip--codex {
  --task-mode-chip-accent: #2563eb;
}

.branch-flow {
  position: relative;
  display: grid;
  gap: 8px;
  min-width: 0;
  padding: 2px 0;
}

.branch-flow::before {
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 4px;
  width: 1px;
  background: rgba(100, 116, 139, 0.24);
  content: '';
}

.branch-flow--direct-only::before {
  display: none;
}

.branch-flow__stage {
  position: relative;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
}

.branch-flow__marker {
  z-index: 1;
  box-sizing: border-box;
  width: 9px;
  height: 9px;
  margin-top: 4px;
  border: 2px solid var(--n-color, #fff);
  border-radius: 50%;
  background: #64748b;
  box-shadow: 0 0 0 1px rgba(100, 116, 139, 0.28);
}

.branch-flow__marker--work {
  background: #059669;
}

.branch-flow__marker--target {
  background: #2563eb;
}

.branch-flow__content {
  display: grid;
  gap: 1px;
  min-width: 0;
}

.branch-flow__label {
  color: var(--n-text-color-3, #8a8f98);
  font-size: 10px;
  line-height: 1.3;
}

.branch-flow__name {
  min-width: 0;
  color: var(--n-text-color-2);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

.branch-flow__mode {
  width: fit-content;
  margin-left: 18px;
  padding: 2px 7px;
  border-radius: 4px;
  background: rgba(100, 116, 139, 0.08);
  color: var(--n-text-color-3, #8a8f98);
  font-size: 10px;
  line-height: 1.4;
}

.time-axis {
  position: relative;
  display: grid;
  gap: 9px;
  min-width: 0;
  padding: 2px 0;
}

.time-axis::before {
  position: absolute;
  top: 8px;
  bottom: 8px;
  left: 4px;
  width: 1px;
  background: rgba(100, 116, 139, 0.22);
  content: '';
}

.time-axis--single::before {
  display: none;
}

.time-point {
  position: relative;
  display: grid;
  grid-template-columns: 10px minmax(0, 1fr);
  gap: 8px;
  min-width: 0;
}

.time-point__marker {
  z-index: 1;
  box-sizing: border-box;
  width: 9px;
  height: 9px;
  margin-top: 4px;
  border: 2px solid var(--n-color, #fff);
  border-radius: 50%;
  background: #94a3b8;
  box-shadow: 0 0 0 1px rgba(100, 116, 139, 0.24);
}

.time-point__marker--scheduled {
  background: #0284c7;
}

.time-point__marker--active {
  background: #d97706;
}

.time-point__marker--complete {
  background: #059669;
}

.time-point__content {
  display: grid;
  grid-template-columns: minmax(54px, max-content) minmax(0, 1fr);
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.time-point__label {
  color: var(--n-text-color-3, #999);
  font-size: 10px;
  letter-spacing: 0;
  line-height: 1.4;
}

.time-point__value {
  color: var(--n-text-color-2);
  font-size: 11px;
  line-height: 1.4;
  overflow-wrap: anywhere;
}

@media (max-width: 600px) {
  .metadata-body {
    grid-template-columns: minmax(74px, max-content) minmax(0, 1fr);
    column-gap: 8px;
    row-gap: 10px;
  }

  .time-point__content {
    grid-template-columns: 1fr;
    gap: 1px;
  }
}

@media (max-width: 420px) {
  .metadata-body {
    grid-template-columns: 1fr;
  }

  .metadata-row {
    display: grid;
    grid-template-columns: 1fr;
    gap: 3px;
  }

  .metadata-label--top {
    padding-top: 0;
  }

  .metadata-value {
    width: 100%;
  }
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}

.metadata-value > .app-link {
  min-width: 0;
  max-width: 100%;
  overflow-wrap: anywhere;
}

.app-link:hover {
  text-decoration: underline;
}

.metadata-reference-link {
  display: inline-flex;
  align-items: baseline;
  gap: 6px;
  flex: 0 1 auto;
  min-width: 0;
  width: fit-content;
  max-width: 100%;
  padding: 2px 0;
  border-bottom: 1px solid color-mix(in srgb, var(--n-primary-color, #18a058) 28%, transparent);
  background: transparent;
  color: var(--n-primary-color, #18a058);
  font-weight: 400;
  line-height: 1.45;
  vertical-align: middle;
  text-decoration: none;
  transition: border-color 0.15s ease, color 0.15s ease;
}

.metadata-reference-link:hover {
  border-color: color-mix(in srgb, var(--n-primary-color, #18a058) 56%, transparent);
  text-decoration: none;
}

.metadata-reference-link__title {
  min-width: 0;
  overflow-wrap: anywhere;
}

.task-issue-link__id {
  flex: 0 0 auto;
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
  font-weight: 500;
}

.task-issue-link__title {
  color: inherit;
}

.metadata-label-icon {
  flex: 0 0 auto;
  opacity: 0.65;
}

.mr-link {
  font-size: 14px;
}

.mr-pending {
  font-size: 13px;
  color: var(--n-text-color-2);
}

.mr-target-branch {
  color: var(--n-text-color-2);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  font-size: 12px;
}

.mr-none {
  font-size: 13px;
  color: var(--n-text-color-3, #999);
  font-style: italic;
}
</style>
