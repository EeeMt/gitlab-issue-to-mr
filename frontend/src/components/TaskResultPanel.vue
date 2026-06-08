<template>
  <n-card class="task-result-panel" :bordered="false">
    <template #header>
      <span class="panel-title">{{ t('taskView.taskResult') }}</span>
    </template>

    <div class="result-body">
      <!-- AI delivery summary (last assistant text event, collapsed by default) -->
      <div v-if="lastAssistantLog" ref="summaryCardRef" class="result-card result-card--summary-text">
        <button
          type="button"
          class="result-card__title summary-header-button"
          :class="{ 'summary-header-button--open': summaryExpanded }"
          :disabled="summaryPayloadLoading"
          :aria-expanded="summaryExpanded"
          @click="toggleSummary"
        >
          <n-icon size="16" class="result-card__icon result-card__icon--summary"><ChatboxOutline /></n-icon>
          <span class="summary-title-label">{{ t('taskView.aiDeliverySummary') }}</span>
          <span v-if="summaryPreview && !summaryExpanded" class="summary-preview">{{ summaryPreview }}</span>
          <span
            class="summary-toggle"
            :class="{ 'summary-toggle--active': summaryExpanded, 'summary-toggle--loading': summaryPayloadLoading }"
          >
            <span class="summary-toggle__label">
              {{ summaryExpanded ? t('taskView.summaryCollapse') : t('taskView.summaryExpand') }}
            </span>
            <span v-if="summaryPayloadLoading" class="badge-spin-ring"></span>
            <n-icon v-else size="11" class="badge-chevron" :class="{ 'badge-chevron--open': summaryExpanded }">
              <ChevronForward />
            </n-icon>
          </span>
        </button>
        <div class="summary-expand-track" :class="{ 'summary-expand-track--open': summaryExpanded }">
          <div class="summary-expand-body">
            <n-scrollbar
              v-if="summaryRenderedHtml"
              class="summary-content-scrollbar"
              x-scrollable
              trigger="hover"
              content-style="min-width: 100%;"
            >
              <div
                ref="summaryContentRef"
                class="summary-content markdown-content"
                @click="handleSummaryContentClick"
                v-html="summaryRenderedHtml"
              ></div>
            </n-scrollbar>
            <n-scrollbar
              v-else-if="!summaryPayloadLoading && summaryPayloadLoaded && !summaryRenderedHtml"
              class="summary-content-scrollbar"
              x-scrollable
              trigger="hover"
              content-style="min-width: 100%;"
            >
              <div class="summary-content summary-content--empty">
                {{ t('taskView.emptyContent') }}
              </div>
            </n-scrollbar>
          </div>
        </div>
        <div v-if="summaryExpanded && !mermaidViewerVisible" class="summary-collapse-footer">
          <n-button class="summary-collapse-button" size="small" secondary round @click="toggleSummary">
            <template #icon>
              <n-icon size="14" class="summary-collapse-button__icon"><ChevronForward /></n-icon>
            </template>
            {{ t('taskView.summaryCollapse') }}
          </n-button>
        </div>
        <div
          v-if="summaryExpanded && !mermaidViewerVisible"
          class="summary-collapse-float"
          :style="summaryCollapseFloatStyle"
        >
          <n-button class="summary-collapse-button" size="small" secondary round @click="toggleSummary">
            <template #icon>
              <n-icon size="14" class="summary-collapse-button__icon"><ChevronForward /></n-icon>
            </template>
            {{ t('taskView.summaryCollapse') }}
          </n-button>
        </div>
      </div>

      <!-- Commit Record Card -->
      <div v-if="task.commit_sha || task.commit_message || hasChanges" class="result-card result-card--commit">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--commit"><GitCommitOutline /></n-icon>
          {{ t('taskView.commitRecord') }}
        </div>
        <div class="result-card__content">
          <div class="commit-meta">
            <a v-if="task.commit_sha && commitUrl" :href="commitUrl" target="_blank" rel="noopener noreferrer" class="commit-sha-chip commit-sha-chip--link">
              <n-icon size="12"><GitCommitOutline /></n-icon>
              <span>{{ task.commit_sha.slice(0, 8) }}</span>
              <n-icon size="11" class="commit-sha-chip__ext"><OpenOutline /></n-icon>
            </a>
            <span v-else-if="task.commit_sha" class="commit-sha-chip">
              <n-icon size="12"><GitCommitOutline /></n-icon>
              <span>{{ task.commit_sha.slice(0, 8) }}</span>
            </span>
          <span v-if="hasChanges" class="commit-stats">
              <span class="changes-add">+{{ task.additions || 0 }}</span>
              <span class="changes-del">-{{ task.deletions || 0 }}</span>
            </span>
          </div>
          <pre v-if="task.commit_message" class="commit-message">{{ task.commit_message }}</pre>
        </div>
      </div>

      <!-- Error Card (for failed tasks) -->
      <div v-if="task.status === 'failed' && task.error_message" class="result-card result-card--error">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--error"><AlertCircleOutline /></n-icon>
          {{ t('taskView.error') }}
        </div>
        <div class="result-card__content">
          <pre class="error-message">{{ task.error_message }}</pre>
        </div>
      </div>

      <!-- Run statistics -->
      <div class="result-card result-card--summary">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon"><TimeOutline /></n-icon>
          {{ t('taskView.runStatistics') }}
        </div>
        <div class="result-card__content summary-grid">
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.modelName') }}</span>
            <span class="summary-value">{{ task.model_name || '-' }}</span>
          </div>
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.totalTokens') }}</span>
            <span class="summary-value">{{ totalTokens != null ? formatLargeNumber(totalTokens) : '-' }}</span>
            <span v-if="task.input_tokens != null && task.output_tokens != null" class="summary-item__sub">
              {{ t('taskView.tokenBreakdown', { input: formatLargeNumber(task.input_tokens), output: formatLargeNumber(task.output_tokens) }) }}
            </span>
          </div>
          <div class="summary-item">
            <span class="summary-label">{{ t('taskView.duration') }}</span>
            <span class="summary-value">{{ executionDuration }}</span>
          </div>
          <div v-if="contextCompactCount != null" class="summary-item">
            <span class="summary-label">{{ t('taskView.contextCompactCount') }}</span>
            <span class="summary-value">{{ t('taskView.contextCompactMetric', { count: contextCompactCount }) }}</span>
          </div>
          <div class="summary-item summary-item--skills">
            <span class="summary-label">{{ t('taskView.skillUsage') }}</span>
            <span class="summary-value">{{ skillUsageTotal > 0 ? t('taskView.skillUsageCount', { count: skillUsageTotal }) : '-' }}</span>
            <span v-if="skillUsageStats.length > 0" class="summary-item__sub skill-usage-list">
              {{ skillUsageBreakdown }}
            </span>
          </div>
        </div>
      </div>

      <!-- Continue Guidance (only for terminal tasks linked to an issue) -->
      <div v-if="['completed', 'failed'].includes(task.status) && task.issue_id" class="result-card result-card--continue">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--continue"><ChatbubbleEllipsesOutline /></n-icon>
          {{ t('taskView.continueGuideTitle') }}
        </div>
        <div class="result-card__content continue-body">
          <p class="continue-hint">{{ t('taskView.continueGuideHint') }}</p>
          <n-button
            type="primary"
            size="small"
            secondary
            strong
            @click="goToIssue"
          >
            <template #icon><n-icon :component="ArrowBackOutline" /></template>
            {{ t('taskView.backToIssue') }}
          </n-button>
        </div>
      </div>

      <!-- Manual Override Card -->
      <div v-if="['completed', 'failed'].includes(task.status)" class="result-card result-card--override">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--override"><ShieldCheckmarkOutline /></n-icon>
          {{ t('taskView.manualOverride') }}
          <n-tag v-if="task.is_manually_overridden" size="tiny" type="warning" :bordered="false" style="margin-left: 6px">
            {{ t('taskView.manuallyOverridden') }}
          </n-tag>
        </div>
        <div class="result-card__content override-body">
          <p class="override-hint">{{ task.is_manually_overridden ? t('taskView.overrideHintAlreadyOverridden', { reason: task.override_reason || t('taskView.overrideNoReason') }) : t('taskView.overrideHint') }}</p>
          <div class="override-actions">
            <n-button
              v-if="task.status === 'completed'"
              size="small"
              type="error"
              secondary
              @click="openOverrideModal('failed')"
            >
              <template #icon><n-icon :component="CloseCircleOutline" /></template>
              {{ t('taskView.markAsFailed') }}
            </n-button>
            <n-button
              v-if="task.status === 'failed'"
              size="small"
              type="success"
              secondary
              @click="openOverrideModal('completed')"
            >
              <template #icon><n-icon :component="CheckmarkCircleOutline" /></template>
              {{ t('taskView.markAsCompleted') }}
            </n-button>
          </div>
        </div>
      </div>
    </div>
  </n-card>

  <!-- Override confirmation modal -->
  <n-modal
    v-model:show="showOverrideModal"
    preset="card"
    class="config-editor-modal"
    :style="{ width: '480px' }"
    :closable="!overrideLoading"
    :mask-closable="!overrideLoading"
  >
    <template #header>
      <span>{{ overrideTargetStatus === 'failed' ? t('taskView.markAsFailed') : t('taskView.markAsCompleted') }}</span>
    </template>
    <n-space vertical :size="16">
      <p style="margin: 0; font-size: 14px; line-height: 1.6; color: var(--n-text-color-2);">
        {{ overrideTargetStatus === 'failed' ? t('taskView.markAsFailedConfirm') : t('taskView.markAsCompletedConfirm') }}
      </p>
      <n-input
        v-model:value="overrideReason"
        type="textarea"
        :rows="3"
        :placeholder="t('taskView.overrideReasonPlaceholder')"
        :disabled="overrideLoading"
      />
      <div style="display: flex; justify-content: flex-end; gap: 8px;">
        <n-button secondary :disabled="overrideLoading" @click="showOverrideModal = false">
          {{ t('common.cancel') }}
        </n-button>
        <n-button
          :type="overrideTargetStatus === 'failed' ? 'error' : 'success'"
          :loading="overrideLoading"
          @click="confirmOverride"
        >
          {{ t('common.confirm') }}
        </n-button>
      </div>
    </n-space>
  </n-modal>

  <!-- Mermaid diagram viewer -->
  <n-modal
    v-model:show="mermaidViewerVisible"
    preset="card"
    class="summary-mermaid-modal"
    :block-scroll="false"
    :style="{ width: 'calc(100vw - 32px)', height: 'calc(100vh - 32px)', maxWidth: 'none' }"
  >
    <div class="summary-mermaid-modal__toolbar">
      <n-button
        v-for="option in mermaidZoomOptions"
        :key="option.value"
        size="tiny"
        secondary
        :type="mermaidZoom === option.value ? 'primary' : 'default'"
        @click="mermaidZoom = option.value"
      >
        {{ option.label }}
      </n-button>
    </div>
    <n-scrollbar
      :key="mermaidViewerScrollbarKey"
      class="summary-mermaid-modal__viewport"
      :class="{ 'summary-mermaid-modal__viewport--dragging': mermaidViewerDragging }"
      x-scrollable
      trigger="none"
      :content-style="mermaidViewerContentStyle"
      @mousedown="handleMermaidViewerMouseDown"
    >
      <div
        class="summary-mermaid-modal__canvas"
        :class="{ 'summary-mermaid-modal__canvas--fit': mermaidZoom === 'fit' }"
        :style="mermaidViewerCanvasStyle"
        v-html="activeMermaidViewerSvg"
      ></div>
    </n-scrollbar>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import type { CSSProperties } from 'vue'
import { NCard, NIcon, NButton, NModal, NInput, NSpace, NTag, NScrollbar, useMessage } from 'naive-ui'
import { AlertCircleOutline, TimeOutline, GitCommitOutline, OpenOutline, ChatbubbleEllipsesOutline, ArrowBackOutline, CheckmarkCircleOutline, CloseCircleOutline, ShieldCheckmarkOutline, ChevronForward, ChatboxOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { formatLargeNumber } from '../utils/usageLimits'
import type { Task, TaskLog } from '../api'
import { overrideTaskStatus, getTaskPayload } from '../api'
import { parseTextEntry, renderMarkdown } from './task-process/taskProcessUtils'
import type { SkillUsageStat } from './task-process/taskProcessUtils'

type MermaidZoom = 'fit' | '100' | '150' | '200' | '300' | '400'

interface SummaryMermaidDiagram {
  source: string
  svg: string
  error: string
}

const props = defineProps<{
  task: Task
  contextCompactCount?: number
  skillUsageStats?: SkillUsageStat[]
  lastAssistantLog?: TaskLog | null
}>()

const emit = defineEmits<{
  (e: 'status-overridden'): void
}>()

const { t } = useI18n()
const router = useRouter()
const message = useMessage()

const showOverrideModal = ref(false)
const overrideTargetStatus = ref<'completed' | 'failed' | null>(null)
const overrideReason = ref('')
const overrideLoading = ref(false)

// Execution summary (last assistant text event)
const summaryExpanded = ref(false)
const summaryPayloadText = ref('')
const summaryPayloadLoading = ref(false)
const summaryPayloadLoaded = ref(false)
const summaryRenderedHtml = ref('')
const summaryRenderedSource = ref('')
const summaryCardRef = ref<HTMLElement | null>(null)
const summaryContentRef = ref<HTMLElement | null>(null)
const summaryMermaidDiagrams = ref<SummaryMermaidDiagram[]>([])
const mermaidViewerVisible = ref(false)
const activeMermaidIndex = ref<number | null>(null)
const mermaidZoom = ref<MermaidZoom>('fit')
const mermaidViewerDragging = ref(false)
const hiddenSummaryCollapseFloatStyle: CSSProperties = {
  display: 'none',
  left: '0px',
  top: '0px',
  visibility: 'hidden',
}
const summaryCollapseFloatStyle = ref<CSSProperties>(hiddenSummaryCollapseFloatStyle)
const summaryCollapseFloatEndThreshold = 160
let mermaidConfigured = false
let mermaidRenderer: typeof import('mermaid').default | null = null
let summaryMermaidRenderRun = 0
let summaryCollapseFloatRaf = 0
let mermaidViewerDrag: {
  container: HTMLElement
  startX: number
  startY: number
  scrollLeft: number
  scrollTop: number
} | null = null

const summaryEntry = computed(() =>
  props.lastAssistantLog ? parseTextEntry(props.lastAssistantLog.metadata) : null
)

const summaryText = computed(() =>
  summaryPayloadLoaded.value ? summaryPayloadText.value : (summaryEntry.value?.text ?? '')
)

const summaryPreview = computed(() => {
  const entry = summaryEntry.value
  if (!entry) return ''
  if (entry.preview) return entry.truncated ? entry.preview + '…' : entry.preview
  return entry.text.slice(0, 120) || ''
})

const mermaidZoomOptions = computed<{ value: MermaidZoom, label: string }[]>(() => [
  { value: 'fit', label: t('taskView.mermaidFitWidth') },
  { value: '100', label: '100%' },
  { value: '150', label: '150%' },
  { value: '200', label: '200%' },
  { value: '300', label: '300%' },
  { value: '400', label: '400%' },
])

const activeMermaidRawSvg = computed(() => {
  if (activeMermaidIndex.value == null) return ''
  return summaryMermaidDiagrams.value[activeMermaidIndex.value]?.svg ?? ''
})

const mermaidViewerSvgWidth = computed(() => {
  return '100%'
})

const mermaidViewerCanvasStyle = computed<CSSProperties>(() => {
  return { width: '100%' }
})

const mermaidViewerContentStyle = computed<CSSProperties>(() => {
  if (mermaidZoom.value === 'fit') {
    return {
      width: '100%',
      minWidth: '100%',
      minHeight: '100%',
      padding: '16px',
      boxSizing: 'border-box',
    }
  }
  return {
    width: `${mermaidZoom.value}%`,
    minWidth: '100%',
    minHeight: '100%',
    padding: '16px',
    boxSizing: 'border-box',
  }
})

const activeMermaidViewerSvg = computed(() =>
  applyMermaidViewerSvgStyle(activeMermaidRawSvg.value, mermaidViewerSvgWidth.value)
)

const mermaidViewerScrollbarKey = computed(() =>
  `${activeMermaidIndex.value ?? 'none'}-${mermaidZoom.value}-${activeMermaidRawSvg.value.length}`
)

function updateSummaryCollapseFloat() {
  summaryCollapseFloatRaf = 0
  const card = summaryCardRef.value
  if (!summaryExpanded.value || mermaidViewerVisible.value || !card) {
    summaryCollapseFloatStyle.value = hiddenSummaryCollapseFloatStyle
    return
  }

  const rect = card.getBoundingClientRect()
  const visibleTop = Math.max(rect.top, 0)
  const visibleBottom = Math.min(rect.bottom, window.innerHeight)
  const nearSummaryEnd = rect.bottom <= window.innerHeight + summaryCollapseFloatEndThreshold
  if (visibleBottom <= visibleTop || nearSummaryEnd) {
    summaryCollapseFloatStyle.value = hiddenSummaryCollapseFloatStyle
    return
  }

  summaryCollapseFloatStyle.value = {
    display: 'flex',
    left: `${rect.left + rect.width / 2}px`,
    top: `${Math.max(visibleTop + 44, visibleBottom - 12)}px`,
    visibility: 'visible',
  }
}

function scheduleSummaryCollapseFloatUpdate() {
  if (summaryCollapseFloatRaf) return
  summaryCollapseFloatRaf = window.requestAnimationFrame(updateSummaryCollapseFloat)
}

onMounted(() => {
  window.addEventListener('scroll', scheduleSummaryCollapseFloatUpdate, true)
  window.addEventListener('resize', scheduleSummaryCollapseFloatUpdate)
})

onBeforeUnmount(() => {
  window.removeEventListener('scroll', scheduleSummaryCollapseFloatUpdate, true)
  window.removeEventListener('resize', scheduleSummaryCollapseFloatUpdate)
  if (summaryCollapseFloatRaf) {
    window.cancelAnimationFrame(summaryCollapseFloatRaf)
  }
  stopMermaidViewerDrag()
})

watch([summaryExpanded, mermaidViewerVisible, summaryRenderedHtml], async () => {
  await nextTick()
  scheduleSummaryCollapseFloatUpdate()
})

watch(mermaidViewerVisible, (visible) => {
  if (!visible) stopMermaidViewerDrag()
})

function applyMermaidViewerSvgStyle(svg: string, width: string): string {
  if (!svg) return ''
  const viewerStyle = `width: ${width}; height: auto; max-width: none; display: block;`
  if (/\sstyle="/i.test(svg)) {
    return svg.replace(/\sstyle="([^"]*)"/i, ` style="$1 ${viewerStyle}"`)
  }
  return svg.replace(/<svg\b/i, `<svg style="${viewerStyle}"`)
}

function escapeHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderSummaryMermaidPlaceholder(index: number): string {
  return [
    `<div class="summary-mermaid" data-summary-mermaid-index="${index}" data-summary-mermaid-state="loading">`,
    '<div class="summary-mermaid__toolbar">',
    '<span class="summary-mermaid__label">Mermaid</span>',
    `<button type="button" class="summary-mermaid__expand" data-summary-mermaid-action="zoom" data-summary-mermaid-index="${index}">${escapeHtml(t('taskView.mermaidOpenLarge'))}</button>`,
    '</div>',
    `<div class="summary-mermaid__canvas" data-summary-mermaid-canvas="${index}">${escapeHtml(t('taskView.mermaidLoading'))}</div>`,
    '</div>',
  ].join('')
}

function renderSummaryMarkdown(text: string): string {
  const diagrams: SummaryMermaidDiagram[] = []
  const mermaidFencePattern = /(^|\n)(`{3,}|~{3,})[ \t]*mermaid[^\n]*\n([\s\S]*?)\n\2[ \t]*(?=\n|$)/gi
  let html = ''
  let lastIndex = 0
  let match: RegExpExecArray | null

  while ((match = mermaidFencePattern.exec(text)) !== null) {
    const prefix = match[1] ?? ''
    const blockStart = match.index + prefix.length
    const before = text.slice(lastIndex, blockStart)
    if (before) html += renderMarkdown(before)

    const source = (match[3] ?? '').trim()
    const index = diagrams.length
    diagrams.push({ source, svg: '', error: '' })
    html += renderSummaryMermaidPlaceholder(index)
    lastIndex = mermaidFencePattern.lastIndex
  }

  const after = text.slice(lastIndex)
  if (after) html += renderMarkdown(after)
  summaryMermaidDiagrams.value = diagrams
  return html || renderMarkdown(text)
}

async function getMermaidRenderer() {
  if (!mermaidRenderer) {
    mermaidRenderer = (await import('mermaid')).default
  }
  if (mermaidConfigured) return mermaidRenderer

  const mermaid = mermaidRenderer
  mermaid.initialize({
    startOnLoad: false,
    theme: 'neutral',
    securityLevel: 'strict',
    flowchart: {
      useMaxWidth: true,
      htmlLabels: true,
    },
  })
  mermaidConfigured = true
  return mermaid
}

function renderMermaidError(source: string, error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  return [
    `<div class="summary-mermaid__error">${escapeHtml(t('taskView.mermaidRenderError'))}</div>`,
    `<pre class="md-code-block hljs"><code>${escapeHtml(source)}</code></pre>`,
    message ? `<div class="summary-mermaid__error-detail">${escapeHtml(message)}</div>` : '',
  ].join('')
}

function resetMermaidViewer() {
  mermaidViewerVisible.value = false
  activeMermaidIndex.value = null
  mermaidZoom.value = 'fit'
  stopMermaidViewerDrag()
}

function isInteractiveMermaidDragTarget(target: EventTarget | null): boolean {
  if (!(target instanceof Element)) return false
  const ignoredSelector = [
    'button',
    'a',
    'input',
    'textarea',
    'select',
    '[role="button"]',
    '.n-scrollbar-rail',
    '.n-scrollbar-rail__scrollbar',
  ].join(', ')
  return Boolean(target.closest(ignoredSelector))
}

function getMermaidViewerScrollContainer(target: EventTarget | null): HTMLElement | null {
  if (!(target instanceof Element)) return null
  const viewport = target.closest('.summary-mermaid-modal__viewport')
  return viewport?.querySelector<HTMLElement>('.n-scrollbar-container') ?? null
}

function handleMermaidViewerMouseDown(event: MouseEvent) {
  if (event.button !== 0 || isInteractiveMermaidDragTarget(event.target)) return

  const container = getMermaidViewerScrollContainer(event.currentTarget)
  if (!container) return
  const canDrag = container.scrollWidth > container.clientWidth || container.scrollHeight > container.clientHeight
  if (!canDrag) return

  mermaidViewerDrag = {
    container,
    startX: event.clientX,
    startY: event.clientY,
    scrollLeft: container.scrollLeft,
    scrollTop: container.scrollTop,
  }
  mermaidViewerDragging.value = true
  event.preventDefault()
  window.addEventListener('mousemove', handleMermaidViewerMouseMove)
  window.addEventListener('mouseup', handleMermaidViewerMouseUp)
}

function handleMermaidViewerMouseMove(event: MouseEvent) {
  if (!mermaidViewerDrag) return

  const deltaX = event.clientX - mermaidViewerDrag.startX
  const deltaY = event.clientY - mermaidViewerDrag.startY
  mermaidViewerDrag.container.scrollLeft = mermaidViewerDrag.scrollLeft - deltaX
  mermaidViewerDrag.container.scrollTop = mermaidViewerDrag.scrollTop - deltaY
  event.preventDefault()
}

function handleMermaidViewerMouseUp() {
  stopMermaidViewerDrag()
}

function stopMermaidViewerDrag() {
  if (!mermaidViewerDrag && !mermaidViewerDragging.value) return
  window.removeEventListener('mousemove', handleMermaidViewerMouseMove)
  window.removeEventListener('mouseup', handleMermaidViewerMouseUp)
  mermaidViewerDrag = null
  mermaidViewerDragging.value = false
}

function markMermaidDiagramError(
  root: HTMLElement,
  diagrams: SummaryMermaidDiagram[],
  index: number,
  error: unknown,
) {
  const diagram = diagrams[index]
  const container = root.querySelector<HTMLElement>(`[data-summary-mermaid-index="${index}"]`)
  const canvas = root.querySelector<HTMLElement>(`[data-summary-mermaid-canvas="${index}"]`)
  if (!diagram || !container || !canvas) return

  diagram.svg = ''
  diagram.error = error instanceof Error ? error.message : String(error)
  canvas.innerHTML = renderMermaidError(diagram.source, error)
  container.dataset.summaryMermaidState = 'error'
}

async function renderSummaryMermaidDiagrams(renderRun: number) {
  const diagrams = summaryMermaidDiagrams.value
  if (diagrams.length === 0) return

  await nextTick()
  if (renderRun !== summaryMermaidRenderRun) return

  const root = summaryContentRef.value
  if (!root) return

  let mermaid: typeof import('mermaid').default
  try {
    mermaid = await getMermaidRenderer()
  } catch (error) {
    if (renderRun !== summaryMermaidRenderRun) return
    diagrams.forEach((_, index) => markMermaidDiagramError(root, diagrams, index, error))
    summaryMermaidDiagrams.value = [...diagrams]
    return
  }
  if (renderRun !== summaryMermaidRenderRun) return

  await Promise.all(diagrams.map(async (diagram, index) => {
    const container = root.querySelector<HTMLElement>(`[data-summary-mermaid-index="${index}"]`)
    const canvas = root.querySelector<HTMLElement>(`[data-summary-mermaid-canvas="${index}"]`)
    if (!container || !canvas) return

    try {
      const renderId = `summary-mermaid-${props.task.id}-${renderRun}-${index}`
      const { svg, bindFunctions } = await mermaid.render(renderId, diagram.source)
      if (renderRun !== summaryMermaidRenderRun) return
      diagram.svg = svg
      diagram.error = ''
      canvas.innerHTML = svg
      bindFunctions?.(canvas)
      container.dataset.summaryMermaidState = 'ready'
    } catch (error) {
      if (renderRun !== summaryMermaidRenderRun) return
      markMermaidDiagramError(root, diagrams, index, error)
    }
  }))

  summaryMermaidDiagrams.value = [...diagrams]
}

function syncSummaryRender() {
  const text = summaryText.value.trim()
  if (!text) {
    summaryMermaidRenderRun += 1
    summaryRenderedHtml.value = ''
    summaryRenderedSource.value = ''
    summaryMermaidDiagrams.value = []
    resetMermaidViewer()
    return
  }
  if (summaryRenderedSource.value === text) return
  const renderRun = ++summaryMermaidRenderRun
  resetMermaidViewer()
  summaryRenderedHtml.value = renderSummaryMarkdown(text)
  summaryRenderedSource.value = text
  if (summaryMermaidDiagrams.value.length === 0) return
  void renderSummaryMermaidDiagrams(renderRun)
}

async function toggleSummary() {
  summaryExpanded.value = !summaryExpanded.value
  if (!summaryExpanded.value) return

  const entry = summaryEntry.value
  if (!entry) return

  if (entry.text) {
    syncSummaryRender()
    return
  }
  if (entry.payloadId && !summaryPayloadLoaded.value && !summaryPayloadLoading.value) {
    summaryPayloadLoading.value = true
    try {
      const payload = await getTaskPayload(props.task.id, entry.payloadId)
      summaryPayloadText.value = payload.content
      summaryPayloadLoaded.value = true
      syncSummaryRender()
    } catch {
      // silently fail; empty state shown
    } finally {
      summaryPayloadLoading.value = false
    }
  }
}

function handleSummaryContentClick(event: MouseEvent) {
  const target = event.target
  if (!(target instanceof HTMLElement)) return

  const button = target.closest<HTMLButtonElement>('[data-summary-mermaid-action="zoom"]')
  if (!button) return

  const index = Number(button.dataset.summaryMermaidIndex)
  if (!Number.isInteger(index)) return
  if (!summaryMermaidDiagrams.value[index]?.svg) return

  activeMermaidIndex.value = index
  mermaidZoom.value = 'fit'
  mermaidViewerVisible.value = true
}

function openOverrideModal(targetStatus: 'completed' | 'failed') {
  overrideTargetStatus.value = targetStatus
  overrideReason.value = ''
  showOverrideModal.value = true
}

async function confirmOverride() {
  if (!overrideTargetStatus.value) return
  overrideLoading.value = true
  try {
    await overrideTaskStatus(props.task.id, overrideTargetStatus.value, overrideReason.value || undefined)
    showOverrideModal.value = false
    emit('status-overridden')
  } catch {
    message.error(t('taskView.failedToOverrideStatus'))
  } finally {
    overrideLoading.value = false
  }
}

function goToIssue() {
  if (props.task.issue_id) {
    router.push(`/issues/${props.task.issue_id}`)
  }
}

const commitUrl = computed(() => {
  if (!props.task.commit_sha || !props.task.project_url) return null
  return `${props.task.project_url}/-/commit/${props.task.commit_sha}`
})

const hasChanges = computed(() =>
  props.task.additions !== undefined || props.task.deletions !== undefined
)

const executionDuration = computed(() => {
  if (!props.task.started_at || !props.task.completed_at) return '-'
  try {
    const startMs = new Date(props.task.started_at).getTime()
    const endMs = new Date(props.task.completed_at).getTime()
    const diffSeconds = Math.max(0, Math.round((endMs - startMs) / 1000))
    if (diffSeconds < 60) return `${diffSeconds}s`
    const minutes = Math.floor(diffSeconds / 60)
    const seconds = diffSeconds % 60
    return seconds > 0 ? `${minutes}m${seconds}s` : `${minutes}m`
  } catch {
    return '-'
  }
})

const totalTokens = computed(() => {
  const i = props.task.input_tokens
  const o = props.task.output_tokens
  if (i == null && o == null) return null
  return (i ?? 0) + (o ?? 0)
})

const skillUsageStats = computed(() => props.skillUsageStats ?? [])

const skillUsageTotal = computed(() =>
  skillUsageStats.value.reduce((total, skill) => total + skill.count, 0)
)

const skillUsageBreakdown = computed(() =>
  skillUsageStats.value
    .map(skill => `${skill.name}: ${t('taskView.skillUsageCount', { count: skill.count })}`)
    .join(' · ')
)
</script>

<style scoped>
.task-result-panel {
  border-radius: var(--app-card-radius);
}

.panel-title {
  font-size: 18px;
  font-weight: 600;
}

.result-body {
  display: grid;
  gap: 14px;
  min-width: 0;
}

.result-card {
  padding: 14px 16px;
  border-radius: 12px;
  border: 1px solid rgba(128, 128, 128, 0.1);
  background: rgba(128, 128, 128, 0.03);
}

.result-card--commit {
  border-color: rgba(59, 130, 246, 0.2);
  background: rgba(59, 130, 246, 0.04);
}

.result-card--error {
  border-color: rgba(239, 68, 68, 0.2);
  background: rgba(239, 68, 68, 0.04);
}

.result-card--summary {
  border-color: rgba(128, 128, 128, 0.12);
}

.result-card__title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-2, #666);
  margin-bottom: 10px;
}

.result-card__icon {
  color: var(--n-text-color-3, #999);
}

.result-card__icon--error {
  color: #ef4444;
}

.result-card__icon--commit {
  color: #3b82f6;
}

.result-card__content {
  font-size: 14px;
}

.error-message {
  margin: 0;
  padding: 10px;
  font-size: 12px;
  font-family: var(--n-font-family-mono, monospace);
  background: rgba(239, 68, 68, 0.06);
  border-radius: 6px;
  white-space: pre-wrap;
  word-break: break-word;
  color: #dc2626;
  max-height: 200px;
  overflow-y: auto;
}

.commit-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 10px;
}

.commit-sha-chip {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-family: var(--n-font-family-mono, monospace);
  font-size: 12.5px;
  font-weight: 600;
  padding: 3px 9px;
  border-radius: 5px;
  background: rgba(59, 130, 246, 0.08);
  border: 1px solid rgba(59, 130, 246, 0.18);
  color: var(--n-text-color-2, #555);
  text-decoration: none;
}

.commit-sha-chip--link {
  color: #3b82f6;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
}

.commit-sha-chip--link:hover {
  background: rgba(59, 130, 246, 0.15);
  border-color: rgba(59, 130, 246, 0.3);
  text-decoration: none;
}

.commit-sha-chip__ext {
  opacity: 0.55;
}

.commit-stats {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-family: var(--n-font-family-mono, monospace);
  font-variant-numeric: tabular-nums;
}

.changes-add {
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(24, 160, 88, 0.25);
  font-size: 12px;
  font-weight: 500;
  background: rgba(24, 160, 88, 0.08);
  color: #18a058;
}

.changes-del {
  padding: 2px 8px;
  border-radius: 4px;
  border: 1px solid rgba(208, 48, 80, 0.22);
  font-size: 12px;
  font-weight: 500;
  background: rgba(208, 48, 80, 0.07);
  color: #d03050;
}

.commit-message {
  margin: 0;
  font-size: 12.5px;
  font-family: var(--n-font-family-mono, monospace);
  padding: 8px 0 0 0;
  border-top: 1px solid rgba(59, 130, 246, 0.15);
  white-space: pre-wrap;
  word-break: break-word;
  color: var(--n-text-color-1, #333);
  line-height: 1.65;
  max-height: 160px;
  overflow-y: auto;
  background: transparent;
}

.summary-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(140px, 1fr));
  gap: 10px;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.summary-label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--n-text-color-3, #999);
}

.summary-value {
  font-size: 14px;
  font-weight: 500;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.summary-value--mono {
  font-family: var(--n-font-family-mono, monospace);
}

.summary-item__sub {
  font-size: 12px;
  color: var(--n-text-color-3, #999);
  margin-top: 2px;
}

.summary-item--skills {
  min-width: 0;
}

.skill-usage-list {
  line-height: 1.45;
  overflow-wrap: anywhere;
}

.result-card--continue {
  border-color: rgba(24, 160, 88, 0.2);
  background: rgba(24, 160, 88, 0.04);
}

.result-card__icon--continue {
  color: #18a058;
}

.continue-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.continue-hint {
  margin: 0;
  font-size: 13px;
  color: var(--n-text-color-2, #555);
  line-height: 1.5;
  flex: 1;
  min-width: 0;
}

.app-link {
  color: var(--n-primary-color, #18a058);
  text-decoration: none;
}
.app-link:hover {
  text-decoration: underline;
}

.result-card--override {
  border-color: rgba(128, 128, 128, 0.15);
  background: rgba(128, 128, 128, 0.03);
}

.result-card__icon--override {
  color: var(--n-text-color-3, #999);
}

.override-body {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.override-hint {
  margin: 0;
  font-size: 13px;
  color: var(--n-text-color-2, #555);
  line-height: 1.5;
  flex: 1;
  min-width: 0;
}

.override-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

/* Execution summary card */
.result-card--summary-text {
  border-color: rgba(2, 132, 199, 0.18);
  background: rgba(2, 132, 199, 0.03);
  min-width: 0;
  padding-bottom: 18px;
  overflow-anchor: none;
}

.result-card--summary-text .result-card__title {
  min-height: 28px;
  margin-bottom: 0;
}

.result-card__icon--summary {
  color: #0284c7;
}

.summary-header-button {
  width: 100%;
  min-width: 0;
  box-sizing: border-box;
  padding: 2px 2px 2px 0;
  border: 0;
  border-radius: 6px;
  background: transparent;
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.summary-header-button:hover {
  background: rgba(2, 132, 199, 0.06);
}

.summary-header-button:focus-visible {
  outline: 2px solid rgba(2, 132, 199, 0.45);
  outline-offset: 2px;
}

.summary-header-button:disabled {
  cursor: wait;
}

.summary-header-button--open {
  color: var(--n-text-color-1, #333);
}

.summary-title-label {
  flex-shrink: 0;
}

.summary-preview {
  flex: 1;
  min-width: 0;
  max-width: 100%;
  font-size: 12px;
  line-height: 22px;
  font-weight: 400;
  color: var(--n-text-color-3, #999);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-left: 4px;
}

.summary-toggle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 52px;
  height: 24px;
  padding: 0 8px;
  margin-left: auto;
  flex-shrink: 0;
  background: rgba(2, 132, 199, 0.08);
  border: 1px solid rgba(2, 132, 199, 0.22);
  border-radius: 4px;
  color: #0284c7;
  transition: color 0.15s, border-color 0.15s, background 0.15s;
  font-family: inherit;
}

.summary-header-button:hover .summary-toggle {
  background: rgba(2, 132, 199, 0.13);
  border-color: rgba(2, 132, 199, 0.36);
}

.summary-toggle__label {
  font-size: 12px;
  line-height: 1;
  font-weight: 500;
  white-space: nowrap;
}

.summary-toggle--active {
  color: var(--n-text-color-2, #555);
  border-color: rgba(128, 128, 128, 0.2);
  background: rgba(128, 128, 128, 0.06);
}

.summary-toggle--loading {
  opacity: 0.72;
}

.badge-chevron {
  transition: transform 0.15s ease;
}

.badge-chevron--open {
  transform: rotate(90deg);
}

.badge-spin-ring {
  display: inline-block;
  width: 10px;
  height: 10px;
  border-radius: 50%;
  border: 1.5px solid currentColor;
  border-top-color: transparent;
  animation: badge-rotate 0.7s linear infinite;
}

@keyframes badge-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.summary-expand-track {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.22s ease;
}

.summary-expand-track--open {
  grid-template-rows: 1fr;
}

.summary-expand-body {
  overflow: hidden;
  min-height: 0;
}

.summary-content-scrollbar {
  margin-top: 10px;
  width: 100%;
  max-width: 100%;
  border-radius: 6px;
}

.summary-content {
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  font-size: 13px;
  line-height: 1.65;
  color: var(--n-text-color-2);
  background: rgba(2, 132, 199, 0.04);
  border-radius: 6px;
  overflow-wrap: break-word;
}

.summary-content--empty {
  font-style: italic;
  opacity: 0.4;
}

.summary-collapse-footer {
  display: flex;
  justify-content: center;
  padding: 12px 0 0;
}

.summary-collapse-float {
  position: fixed;
  z-index: 2400;
  display: flex;
  justify-content: center;
  transform: translate(-50%, -100%);
  pointer-events: none;
}

.summary-collapse-button {
  pointer-events: auto;
  box-shadow: 0 10px 26px rgba(15, 23, 42, 0.18);
  backdrop-filter: blur(8px);
}

.summary-collapse-button__icon {
  transform: rotate(-90deg);
}

/* reuse markdown styles for summary content */
.summary-content :deep(p) { margin: 0 0 0.6em; }
.summary-content :deep(p:last-child) { margin-bottom: 0; }
.summary-content :deep(h1), .summary-content :deep(h2),
.summary-content :deep(h3), .summary-content :deep(h4) {
  margin: 0.8em 0 0.4em; font-weight: 600; line-height: 1.3;
}
.summary-content :deep(h1) { font-size: 1.25em; }
.summary-content :deep(h2) { font-size: 1.1em; }
.summary-content :deep(h3) { font-size: 1em; }
.summary-content :deep(ul), .summary-content :deep(ol) { margin: 0.4em 0; padding-left: 1.5em; }
.summary-content :deep(li) { margin: 0.15em 0; }
.summary-content :deep(code) {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.88em;
  background: rgba(128, 128, 128, 0.12);
  border-radius: 3px;
  padding: 0.1em 0.35em;
}
.summary-content :deep(pre.md-code-block) {
  margin: 0.5em 0; padding: 10px 12px;
  background: rgba(0, 0, 0, 0.06); border-radius: 5px;
  font-family: var(--n-font-family-mono, monospace);
  font-size: 0.85em; line-height: 1.55; white-space: pre;
}
.summary-content :deep(pre.md-code-block code) { background: none; padding: 0; border-radius: 0; font-size: inherit; color: inherit; }
.summary-content :deep(a) { color: var(--n-primary-color, #18a058); text-decoration: none; }
.summary-content :deep(a:hover) { text-decoration: underline; }
.summary-content :deep(blockquote) {
  margin: 0.5em 0; padding: 0.2em 0.8em;
  border-left: 3px solid var(--n-border-color, rgba(128,128,128,0.35));
  color: var(--n-text-color-3, #888);
}

.summary-content :deep(.summary-mermaid) {
  margin: 0.7em 0;
  border: 1px solid rgba(2, 132, 199, 0.16);
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.6);
  overflow: hidden;
}

.summary-content :deep(.summary-mermaid__toolbar) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-bottom: 1px solid rgba(2, 132, 199, 0.12);
  background: rgba(2, 132, 199, 0.04);
}

.summary-content :deep(.summary-mermaid__label) {
  font-size: 12px;
  font-weight: 600;
  color: var(--n-text-color-3, #777);
}

.summary-content :deep(.summary-mermaid__expand) {
  border: 1px solid rgba(2, 132, 199, 0.22);
  border-radius: 4px;
  padding: 2px 8px;
  background: rgba(2, 132, 199, 0.08);
  color: #0284c7;
  font: inherit;
  font-size: 12px;
  line-height: 18px;
  cursor: pointer;
}

.summary-content :deep(.summary-mermaid__expand:hover) {
  background: rgba(2, 132, 199, 0.14);
  border-color: rgba(2, 132, 199, 0.36);
}

.summary-content :deep(.summary-mermaid[data-summary-mermaid-state="loading"] .summary-mermaid__expand),
.summary-content :deep(.summary-mermaid[data-summary-mermaid-state="error"] .summary-mermaid__expand) {
  display: none;
}

.summary-content :deep(.summary-mermaid__canvas) {
  min-height: 96px;
  max-height: 60vh;
  padding: 12px;
  overflow: auto;
  color: var(--n-text-color-2);
}

.summary-content :deep(.summary-mermaid__canvas svg) {
  display: block;
  max-width: none;
}

.summary-content :deep(.summary-mermaid__error) {
  margin-bottom: 8px;
  color: #d03050;
  font-weight: 600;
}

.summary-content :deep(.summary-mermaid__error-detail) {
  margin-top: 6px;
  color: var(--n-text-color-3, #888);
  font-family: var(--n-font-family-mono, monospace);
  font-size: 12px;
  white-space: pre-wrap;
}

:global(.summary-mermaid-modal) {
  display: flex;
  flex-direction: column;
  max-width: none;
  position: relative;
}

:global(.summary-mermaid-modal .n-card-header) {
  position: absolute;
  top: 10px;
  right: 10px;
  z-index: 1;
  padding: 0;
}

:global(.summary-mermaid-modal .n-card-content) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding-top: 12px;
}

:global(.summary-mermaid-modal__toolbar) {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  padding-right: 36px;
  margin-bottom: 10px;
}

:global(.summary-mermaid-modal__viewport) {
  flex: 1 1 auto;
  height: 0;
  min-height: 0;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.18));
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.72);
  cursor: grab;
  user-select: none;
  overscroll-behavior: contain;
}

:global(.summary-mermaid-modal__viewport--dragging) {
  cursor: grabbing;
}

:global(.summary-mermaid-modal__viewport--dragging *) {
  cursor: grabbing;
}

:global(.summary-mermaid-modal__viewport .n-scrollbar-container) {
  min-height: 0;
  max-height: 100%;
}

:global(.summary-mermaid-modal__canvas) {
  min-width: 100%;
}

:global(.summary-mermaid-modal__canvas svg) {
  display: block;
  height: auto;
  max-width: none;
}

:global(.summary-mermaid-modal__canvas--fit svg) {
  max-width: 100%;
}
</style>
