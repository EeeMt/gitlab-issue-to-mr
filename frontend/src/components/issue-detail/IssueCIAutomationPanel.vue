<template>
  <n-card class="ci-panel" :bordered="false" data-testid="issue-ci-failures-card">
    <template #header>
      <div class="ci-panel__header">
        <div>
          <div class="ci-panel__eyebrow">{{ t('issue.automationOperations') }}</div>
          <div class="ci-panel__title">{{ t('issue.ciAutomation') }}</div>
        </div>
        <n-tag size="small" round :type="enabled ? 'success' : 'default'">
          {{ enabled ? t('issue.ciAutoRepairOn') : t('issue.ciAutoRepairOff') }}
        </n-tag>
      </div>
    </template>

    <div v-if="loading" class="ci-panel__empty">{{ t('common.loading') }}</div>
    <div v-else-if="failures.length === 0" class="ci-panel__empty">{{ t('issue.noCiAutomationEvents') }}</div>
    <div v-else class="ci-panel__content">
      <div class="ci-automation-summary" aria-live="polite">
        <div class="ci-automation-summary__item">
          <span>{{ t('issue.ciFailuresDetected') }}</span>
          <strong>{{ total || failures.length }}</strong>
        </div>
        <div class="ci-automation-summary__item">
          <span>{{ t('issue.ciLatestStatus') }}</span>
          <strong>{{ latestFailure ? statusLabel(latestFailure.status) : '—' }}</strong>
        </div>
        <div class="ci-automation-summary__item">
          <span>{{ t('issue.ciRepairTasks') }}</span>
          <strong>{{ repairTaskCount }}</strong>
        </div>
        <div class="ci-automation-summary__item">
          <span>{{ t('issue.ciRootCauseJobs') }}</span>
          <strong>{{ rootCauseJobCount }}</strong>
        </div>
      </div>

      <n-scrollbar
        class="ci-panel__scrollbar"
        trigger="hover"
        content-style="padding-right: 10px;"
      >
        <div class="ci-run-list">
          <article v-for="run in visibleFailures" :key="run.id" class="ci-failure-run">
            <div class="ci-failure-run__header">
              <div class="ci-failure-run__identity">
                <span class="ci-failure-run__time">{{ formatCompactDateTime(run.created_at) }}</span>
                <a
                  v-if="run.pipeline_url"
                  :href="run.pipeline_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="ci-failure-run__pipeline ci-link"
                >
                  {{ t('issue.pipelineLabel', { id: run.pipeline_id }) }} ↗
                </a>
                <span v-else class="ci-failure-run__pipeline">
                  {{ t('issue.pipelineLabel', { id: run.pipeline_id }) }}
                </span>
                <span class="ci-failure-run__ref">
                  {{ run.pipeline_ref || run.source_branch || '—' }}
                  <template v-if="run.pipeline_sha"> · {{ shortSha(run.pipeline_sha) }}</template>
                </span>
              </div>

              <div class="ci-failure-run__actions">
                <n-tag size="small" round :type="statusTagType(run.status)">
                  {{ statusLabel(run.status) }}
                </n-tag>
                <n-tag v-if="run.ignored_reason" size="small" round>
                  {{ ignoredReasonLabel(run.ignored_reason) }}
                </n-tag>
                <span class="ci-failure-run__attempts">
                  {{ t('issue.ciCollectionAttempts', { count: run.collection_attempts }) }}
                </span>
                <n-button
                  v-if="run.repair_task_id"
                  size="tiny"
                  text
                  type="primary"
                  @click="emit('open-task', run.repair_task_id)"
                >
                  {{ t('issue.viewRepairTask', { id: run.repair_task_id }) }}
                </n-button>
              </div>
            </div>

            <div class="ci-failure-run__body">
              <section class="ci-run-section">
                <div class="ci-run-section__title">{{ t('issue.ciFailedJobs') }}</div>
                <div v-if="run.jobs?.length" class="ci-job-list">
                  <component
                    :is="job.web_url ? 'a' : 'span'"
                    v-for="job in sortedJobs(run)"
                    :key="job.id"
                    :href="job.web_url || undefined"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="ci-job-chip"
                    :class="{
                      'ci-job-chip--root': job.is_root_cause,
                      'ci-job-chip--infra': job.is_root_cause && job.classification === 'infra',
                    }"
                  >
                    <span class="ci-job-chip__name">{{ job.name }} · {{ job.classification }}</span>
                    <span v-if="job.stage" class="ci-job-chip__meta">{{ job.stage }}</span>
                  </component>
                </div>
                <div v-else class="ci-run-section__empty">{{ t('issue.ciNoFailedJobs') }}</div>
              </section>

              <section class="ci-run-section">
                <div class="ci-run-section__title">{{ t('issue.ciProcessingTimeline') }}</div>
                <div v-if="hasTimeline(run)" class="ci-run-timeline">
                  <div v-if="webhookEventsByRun[run.id]" class="ci-run-timeline__item ci-failure-run__webhook-step">
                    <span class="ci-run-timeline__time">{{ formatTimelineTime(webhookEventsByRun[run.id].created_at) }}</span>
                    <span class="ci-run-timeline__step">{{ t('issue.ciWebhookReceived') }}</span>
                    <span v-if="webhookEventsByRun[run.id].result_detail" class="ci-run-timeline__message">
                      {{ webhookEventsByRun[run.id].result_detail }}
                    </span>
                  </div>
                  <div v-for="log in run.logs ?? []" :key="log.id" class="ci-run-timeline__item">
                    <span class="ci-run-timeline__time">{{ formatTimelineTime(log.created_at) }}</span>
                    <span class="ci-run-timeline__step">{{ log.step }}</span>
                    <n-tag size="tiny" round>{{ log.status }}</n-tag>
                    <span v-if="log.message" class="ci-run-timeline__message">{{ log.message }}</span>
                  </div>
                </div>
                <div v-else class="ci-run-section__empty">{{ t('issue.ciNoTimeline') }}</div>
              </section>
            </div>

            <div v-if="run.error_message" class="ci-run-error">
              <span>{{ t('issue.ciCollectorError') }}</span>
              <strong>{{ run.error_message }}</strong>
            </div>
          </article>
        </div>
      </n-scrollbar>

      <n-button
        v-if="failures.length > 1"
        class="ci-panel__toggle"
        text
        type="primary"
        size="small"
        @click="showAll = !showAll"
      >
        {{ showAll ? t('issue.collapseCiHistory') : t('issue.expandCiHistory', { count: failures.length }) }}
      </n-button>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { NButton, NCard, NScrollbar, NTag } from 'naive-ui'
import { useI18n } from 'vue-i18n'
import type { CIFailureRun, WebhookEvent } from '../../api'
import { formatDateTimeUtc8Compact, formatTimeUtc8 } from '../../utils/datetime'

const props = defineProps<{
  enabled: boolean
  failures: CIFailureRun[]
  loading: boolean
  total: number
  repairTaskCount: number
  rootCauseJobCount: number
  webhookEventsByRun: Record<number, WebhookEvent>
}>()

const emit = defineEmits<{
  (event: 'open-task', taskId: number): void
}>()

const { t } = useI18n()
const showAll = ref(false)
const latestFailure = computed(() => props.failures[0] ?? null)
const visibleFailures = computed(() => showAll.value ? props.failures : props.failures.slice(0, 1))

function statusLabel(status: string): string {
  return t(`issue.ciFailureStatus.${status}`)
}

function statusTagType(status: string): 'default' | 'info' | 'warning' | 'success' | 'error' {
  if (status === 'task_created') return 'success'
  if (status === 'failed') return 'error'
  if (status === 'ignored') return 'warning'
  if (status === 'collecting' || status === 'collected') return 'info'
  return 'default'
}

function ignoredReasonLabel(reason: string): string {
  return t(`issue.ciIgnoredReason.${reason}`)
}

function sortedJobs(run: CIFailureRun) {
  return [...(run.jobs ?? [])].sort((a, b) => Number(b.is_root_cause) - Number(a.is_root_cause))
}

function hasTimeline(run: CIFailureRun): boolean {
  return Boolean(props.webhookEventsByRun[run.id] || run.logs?.length)
}

function shortSha(value: string): string {
  return value.slice(0, 8)
}

function formatCompactDateTime(value?: string | null): string {
  return value ? formatDateTimeUtc8Compact(value) : '—'
}

function formatTimelineTime(value?: string | null): string {
  return value ? formatTimeUtc8(value) : '—'
}
</script>

<style scoped>
.ci-panel {
  max-height: 744px;
  border-radius: var(--app-card-radius);
}

.ci-panel :deep(.n-card-content) {
  display: flex;
  min-height: 0;
  flex: 1;
  overflow: hidden;
  flex-direction: column;
}

.ci-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.ci-panel__eyebrow {
  margin-bottom: 3px;
  color: var(--n-text-color-3);
  font-size: 11px;
  font-weight: 650;
  letter-spacing: 0.07em;
  text-transform: uppercase;
}

.ci-panel__title {
  color: var(--n-text-color-1);
  font-size: 18px;
  font-weight: 650;
}

.ci-panel__empty {
  display: flex;
  min-height: 96px;
  align-items: center;
  justify-content: center;
  color: var(--n-text-color-3);
  font-size: 13px;
}

.ci-panel__content {
  display: grid;
  grid-template-rows: auto minmax(0, 1fr) auto;
  gap: 12px;
  min-height: 0;
}

.ci-panel__scrollbar {
  max-height: 516px;
}

.ci-panel__toggle {
  justify-self: start;
}

.ci-automation-summary {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}

.ci-automation-summary__item {
  display: grid;
  gap: 3px;
  min-width: 0;
  padding: 9px 10px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 6px;
  background: rgba(248, 250, 252, 0.72);
}

.ci-automation-summary__item span {
  overflow: hidden;
  color: var(--n-text-color-3);
  font-size: 12px;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-automation-summary__item strong {
  overflow: hidden;
  color: rgba(15, 23, 42, 0.86);
  font-size: 18px;
  font-weight: 650;
  line-height: 1.15;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-run-list {
  display: grid;
  gap: 10px;
}

.ci-failure-run {
  display: grid;
  gap: 12px;
  padding: 12px;
  border: 1px solid rgba(148, 163, 184, 0.2);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.78);
}

.ci-failure-run__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.ci-failure-run__identity {
  display: grid;
  gap: 3px;
  min-width: 180px;
}

.ci-failure-run__pipeline {
  font-weight: 650;
  line-height: 1.3;
}

.ci-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}

.ci-failure-run__time,
.ci-failure-run__ref,
.ci-failure-run__attempts,
.ci-run-timeline__time {
  color: var(--n-text-color-3);
  font-size: 12px;
}

.ci-failure-run__ref {
  max-width: 440px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-failure-run__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 6px;
  flex: 1 1 260px;
  flex-wrap: wrap;
}

.ci-failure-run__attempts {
  line-height: 22px;
  white-space: nowrap;
}

.ci-failure-run__body {
  display: grid;
  grid-template-columns: minmax(200px, 0.8fr) minmax(0, 1.2fr);
  gap: 12px;
  align-items: start;
}

.ci-run-section {
  display: grid;
  gap: 7px;
  min-width: 0;
}

.ci-run-section__title {
  color: rgba(15, 23, 42, 0.68);
  font-size: 12px;
  font-weight: 650;
}

.ci-run-section__empty,
.ci-run-timeline {
  padding: 7px 8px;
  border-radius: 6px;
  background: rgba(15, 23, 42, 0.025);
}

.ci-run-section__empty {
  display: flex;
  min-height: 30px;
  align-items: center;
  color: var(--n-text-color-3);
  font-size: 12px;
}

.ci-job-list {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.ci-job-chip {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
  max-width: 100%;
  padding: 4px 8px;
  border: 1px solid rgba(148, 163, 184, 0.28);
  border-radius: 999px;
  background: rgba(248, 250, 252, 0.86);
  color: rgba(51, 65, 85, 0.9);
  font-size: 12px;
  text-decoration: none;
}

.ci-job-chip--root {
  border-color: rgba(208, 48, 80, 0.26);
  background: rgba(208, 48, 80, 0.06);
  color: #9f1d38;
}

.ci-job-chip--infra {
  border-color: rgba(240, 160, 32, 0.32);
  background: rgba(240, 160, 32, 0.08);
  color: #8a5a00;
}

.ci-job-chip__name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-job-chip__meta {
  flex: 0 0 auto;
  color: var(--n-text-color-3);
}

.ci-run-timeline {
  display: grid;
  gap: 5px;
}

.ci-run-timeline__item {
  display: grid;
  grid-template-columns: 38px minmax(0, 1fr) max-content;
  align-items: center;
  column-gap: 8px;
  row-gap: 2px;
  min-width: 0;
  font-size: 12px;
  line-height: 1.35;
}

.ci-run-timeline__time { grid-column: 1; }

.ci-run-timeline__step {
  grid-column: 2;
  overflow: hidden;
  min-width: 0;
  color: var(--n-text-color-2);
  font-family: var(--n-font-family-mono, 'JetBrains Mono', monospace);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-run-timeline__item :deep(.n-tag) {
  grid-column: 3;
  justify-self: end;
  max-width: 86px;
}

.ci-run-timeline__message {
  grid-column: 2 / 4;
  overflow: hidden;
  min-width: 0;
  color: var(--n-text-color-3);
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ci-failure-run__webhook-step {
  margin-bottom: 3px;
  padding-bottom: 6px;
  border-bottom: 1px dashed rgba(148, 163, 184, 0.22);
}

.ci-run-error {
  display: grid;
  gap: 3px;
  padding: 8px 10px;
  border-radius: 6px;
  background: rgba(208, 48, 80, 0.06);
  color: #9f1d38;
  font-size: 12px;
}

.ci-run-error span { font-weight: 650; }
.ci-run-error strong { font-weight: 500; }

@media (max-width: 768px) {
  .ci-panel { max-height: none; }
  .ci-panel__scrollbar { max-height: 624px; }
  .ci-automation-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .ci-failure-run__body { grid-template-columns: minmax(0, 1fr); }
}
</style>
