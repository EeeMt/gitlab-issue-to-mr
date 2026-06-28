<template>
  <n-card class="task-result-panel" :bordered="false">
    <template #header>
      <div class="panel-heading">
        <div class="panel-eyebrow">{{ t('taskView.executionConclusion') }}</div>
        <div class="panel-title">{{ t('taskView.taskResult') }}</div>
      </div>
    </template>

    <div class="result-body">
      <!-- Failed tasks lead with the blocking error. -->
      <div v-if="task.status === 'failed' && task.error_message" class="result-card result-card--error">
        <div class="result-card__title">
          <n-icon size="16" class="result-card__icon result-card__icon--error"><AlertCircleOutline /></n-icon>
          {{ t('taskView.error') }}
        </div>
        <div class="result-card__content">
          <pre class="error-message">{{ task.error_message }}</pre>
        </div>
      </div>

      <!-- AI delivery summary (collapsed by default) -->
      <div v-if="selectedSummaryLog" ref="summaryCardRef" class="result-card result-card--summary-text">
        <button
          type="button"
          class="summary-trigger"
          :class="{ 'summary-trigger--expanded': summaryExpanded }"
          :disabled="summaryPayloadLoading"
          :aria-expanded="summaryExpanded"
          @click="toggleSummary"
        >
          <div class="summary-trigger__leading">
            <div class="summary-trigger__icon-wrap">
              <span v-if="summaryPayloadLoading" class="badge-spin-ring badge-spin-ring--accent"></span>
              <n-icon v-else size="18" class="summary-trigger__icon"><ChatboxOutline /></n-icon>
            </div>
            <div class="summary-trigger__text" :class="{ 'summary-trigger__text--has-preview': summaryPreview }">
              <span class="summary-trigger__title">{{ t('taskView.aiDeliverySummary') }}</span>
              <span class="summary-trigger__preview">{{ summaryPreview }}</span>
            </div>
          </div>
          <div class="summary-trigger__actions">
            <n-tooltip trigger="hover">
              <template #trigger>
                <span
                  class="summary-trigger__action-btn"
                  role="button"
                  tabindex="0"
                  :aria-label="t('taskView.summaryOpenLarge')"
                  @click.stop="openSummaryViewer"
                  @keydown.enter.stop="openSummaryViewer"
                >
                  <n-icon size="15"><ExpandOutline /></n-icon>
                </span>
              </template>
              {{ t('taskView.summaryOpenLarge') }}
            </n-tooltip>
            <span class="summary-trigger__chevron" :class="{ 'summary-trigger__chevron--open': summaryExpanded }">
              <n-icon size="14"><ChevronForward /></n-icon>
            </span>
          </div>
        </button>
        <div class="summary-expand-track" :class="{ 'summary-expand-track--open': summaryExpanded }">
          <div class="summary-expand-body">
            <n-scrollbar
              v-if="summaryRenderedHtml"
              class="summary-content-scrollbar"
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
              trigger="hover"
              content-style="min-width: 100%;"
            >
              <div class="summary-content summary-content--empty">
                {{ t('taskView.emptyContent') }}
              </div>
            </n-scrollbar>
          </div>
        </div>
        <div v-if="summaryExpanded && !mermaidViewerVisible && !summaryViewerVisible" class="summary-collapse-footer">
          <n-button class="summary-collapse-button" size="small" secondary round @click="toggleSummary">
            <template #icon>
              <n-icon size="14" class="summary-collapse-button__icon"><ChevronForward /></n-icon>
            </template>
            {{ t('taskView.summaryCollapse') }}
          </n-button>
        </div>
        <div
          v-if="summaryExpanded && !mermaidViewerVisible && !summaryViewerVisible"
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

    </div>
  </n-card>

  <!-- Full summary viewer for long mixed text and diagrams. -->
  <n-modal
    v-model:show="summaryViewerVisible"
    preset="card"
    class="summary-content-modal"
    :style="{ width: 'min(1320px, calc(100vw - 32px))', height: 'calc(100vh - 32px)', maxWidth: 'none' }"
  >
    <template #header>
      <div class="summary-content-modal__title">
        <span class="viewer-modal__title-icon summary-content-modal__title-icon">
          <n-icon size="18"><ChatboxOutline /></n-icon>
        </span>
        <span>{{ t('taskView.aiDeliverySummary') }}</span>
      </div>
    </template>
    <n-scrollbar
      class="summary-content-modal__viewport"
      trigger="hover"
      content-style="min-width: 100%; padding: 20px 24px 32px; box-sizing: border-box;"
    >
      <div
        v-if="summaryRenderedHtml"
        ref="summaryViewerContentRef"
        class="summary-content summary-content--viewer markdown-content"
        @click="handleSummaryContentClick"
        v-html="summaryRenderedHtml"
      ></div>
      <div v-else class="summary-content summary-content--viewer summary-content--empty">
        {{ t('taskView.emptyContent') }}
      </div>
    </n-scrollbar>
  </n-modal>

  <!-- Mermaid diagram viewer -->
  <n-modal
    v-model:show="mermaidViewerVisible"
    preset="card"
    class="summary-mermaid-modal"
    :block-scroll="false"
    :style="{ width: 'calc(100vw - 32px)', height: 'calc(100vh - 32px)', maxWidth: 'none' }"
  >
    <template #header>
      <div class="summary-mermaid-modal__header">
        <div class="summary-mermaid-modal__title">
          <span class="viewer-modal__title-icon summary-mermaid-modal__title-icon">
            <n-icon size="18"><ExpandOutline /></n-icon>
          </span>
          <span>Mermaid</span>
        </div>
        <div class="summary-mermaid-modal__toolbar">
          <div class="summary-mermaid-modal__zoom-group">
            <n-button
              v-for="option in mermaidZoomOptions"
              :key="option.value"
              size="tiny"
              secondary
              :type="mermaidZoom === option.value ? 'primary' : 'default'"
              @click="selectMermaidZoom(option.value)"
            >
              {{ option.label }}
            </n-button>
            <n-input-number
              class="summary-mermaid-modal__custom-zoom"
              :value="mermaidCustomZoom"
              size="tiny"
              :min="mermaidZoomMin"
              :max="mermaidZoomMax"
              :step="10"
              :show-button="false"
              @focus="mermaidZoom = 'custom'"
              @update:value="handleMermaidCustomZoom"
            >
              <template #suffix>%</template>
            </n-input-number>
          </div>
        </div>
      </div>
    </template>
    <n-scrollbar
      :key="mermaidViewerScrollbarKey"
      class="summary-mermaid-modal__viewport"
      :class="{ 'summary-mermaid-modal__viewport--dragging': mermaidViewerDragging }"
      x-scrollable
      trigger="none"
      :content-style="mermaidViewerContentStyle"
      @mousedown="handleMermaidViewerMouseDown"
      @wheel.prevent="handleMermaidViewerWheel"
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
import { NCard, NIcon, NButton, NInputNumber, NModal, NScrollbar, NTooltip } from 'naive-ui'
import { AlertCircleOutline, GitCommitOutline, OpenOutline, ChevronForward, ChatboxOutline, ExpandOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'
import type { Task, TaskLog } from '../api'
import { getTaskPayload } from '../api'
import { parseTextEntry, renderMarkdown } from './task-process/taskProcessUtils'

type MermaidZoom = 'fit' | '100' | '150' | '200' | '300' | 'custom'

interface SummaryMermaidDiagram {
  source: string
  svg: string
  error: string
}

const props = defineProps<{
  task: Task
  deliverySummaryLog?: TaskLog | null
  lastAssistantLog?: TaskLog | null
}>()

const { t } = useI18n()

// Delivery summary, falling back to the last assistant text event for older tasks.
const summaryExpanded = ref(false)
const summaryPayloadText = ref('')
const summaryPayloadLoading = ref(false)
const summaryPayloadLoaded = ref(false)
const summaryRenderedHtml = ref('')
const summaryRenderedSource = ref('')
const summaryCardRef = ref<HTMLElement | null>(null)
const summaryContentRef = ref<HTMLElement | null>(null)
const summaryViewerContentRef = ref<HTMLElement | null>(null)
const summaryViewerVisible = ref(false)
const summaryMermaidDiagrams = ref<SummaryMermaidDiagram[]>([])
const mermaidViewerVisible = ref(false)
const activeMermaidIndex = ref<number | null>(null)
const mermaidZoomMin = 10
const mermaidZoomMax = 2000
const mermaidZoom = ref<MermaidZoom>('fit')
const mermaidCustomZoom = ref(100)
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

const selectedSummaryLog = computed(() =>
  props.deliverySummaryLog ?? props.lastAssistantLog ?? null
)

const summaryEntry = computed(() =>
  selectedSummaryLog.value ? parseTextEntry(selectedSummaryLog.value.metadata) : null
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
])

const mermaidZoomPercent = computed(() => {
  if (mermaidZoom.value === 'fit') return 100
  return mermaidZoom.value === 'custom'
    ? mermaidCustomZoom.value
    : Number(mermaidZoom.value)
})

const activeMermaidRawSvg = computed(() => {
  if (activeMermaidIndex.value == null) return ''
  return summaryMermaidDiagrams.value[activeMermaidIndex.value]?.svg ?? ''
})

const mermaidViewerSvgWidth = computed(() => {
  return '100%'
})

const mermaidViewerCanvasStyle = computed<CSSProperties>(() => {
  const canvasZoom = mermaidZoom.value === 'fit'
    ? 100
    : Math.min(100, mermaidZoomPercent.value)
  return {
    width: `${canvasZoom}%`,
    margin: '0 auto',
  }
})

const mermaidViewerContentStyle = computed<CSSProperties>(() => {
  const contentZoom = mermaidZoom.value === 'fit'
    ? 100
    : Math.max(100, mermaidZoomPercent.value)
  return {
    width: `${contentZoom}%`,
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
  `${activeMermaidIndex.value ?? 'none'}-${mermaidZoom.value}-${mermaidCustomZoom.value}-${activeMermaidRawSvg.value.length}`
)

function handleMermaidCustomZoom(value: number | null) {
  if (value == null) return
  const nextZoom = clampMermaidZoom(value)
  mermaidCustomZoom.value = nextZoom
  mermaidZoom.value = 'custom'
}

function clampMermaidZoom(value: number) {
  return Math.min(mermaidZoomMax, Math.max(mermaidZoomMin, Math.round(value)))
}

function selectMermaidZoom(value: MermaidZoom) {
  mermaidZoom.value = value
  if (value === 'fit') {
    mermaidCustomZoom.value = 100
  } else if (value !== 'custom') {
    mermaidCustomZoom.value = Number(value)
  }
}

function updateSummaryCollapseFloat() {
  summaryCollapseFloatRaf = 0
  const card = summaryCardRef.value
  if (!summaryExpanded.value || mermaidViewerVisible.value || summaryViewerVisible.value || !card) {
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

watch([summaryExpanded, mermaidViewerVisible, summaryViewerVisible, summaryRenderedHtml], async () => {
  await nextTick()
  scheduleSummaryCollapseFloatUpdate()
})

watch(mermaidViewerVisible, (visible) => {
  if (!visible) stopMermaidViewerDrag()
})

watch([summaryViewerVisible, summaryRenderedHtml, summaryMermaidDiagrams], async () => {
  if (!summaryViewerVisible.value) return
  await nextTick()
  hydrateSummaryViewerMermaid()
})

watch(() => selectedSummaryLog.value?.id ?? null, async () => {
  summaryPayloadText.value = ''
  summaryPayloadLoading.value = false
  summaryPayloadLoaded.value = false
  summaryRenderedHtml.value = ''
  summaryRenderedSource.value = ''
  summaryMermaidDiagrams.value = []
  summaryViewerVisible.value = false
  resetMermaidViewer()
  if (summaryExpanded.value) {
    await loadSummaryPayloadIfNeeded()
  }
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
  selectMermaidZoom('fit')
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

async function handleMermaidViewerWheel(event: WheelEvent) {
  if (event.deltaY === 0) return

  const container = getMermaidViewerScrollContainer(event.currentTarget)
  const viewport = event.currentTarget instanceof Element ? event.currentTarget : null
  const modal = viewport?.closest('.summary-mermaid-modal')
  if (!container || !modal) return

  const rect = container.getBoundingClientRect()
  const pointerX = Math.min(container.clientWidth, Math.max(0, event.clientX - rect.left))
  const pointerY = Math.min(container.clientHeight, Math.max(0, event.clientY - rect.top))
  const currentZoom = mermaidZoomPercent.value
  const zoomFactor = event.deltaY < 0 ? 1.1 : 1 / 1.1
  const nextZoom = clampMermaidZoom(currentZoom * zoomFactor)
  if (nextZoom === currentZoom) return

  const zoomRatio = nextZoom / currentZoom
  const nextScrollLeft = (container.scrollLeft + pointerX) * zoomRatio - pointerX
  const nextScrollTop = (container.scrollTop + pointerY) * zoomRatio - pointerY
  mermaidCustomZoom.value = nextZoom
  mermaidZoom.value = 'custom'

  await nextTick()
  const nextContainer = modal.querySelector<HTMLElement>('.summary-mermaid-modal__viewport .n-scrollbar-container')
  if (!nextContainer) return
  nextContainer.scrollLeft = Math.max(0, nextScrollLeft)
  nextContainer.scrollTop = Math.max(0, nextScrollTop)
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

function hydrateSummaryViewerMermaid() {
  const root = summaryViewerContentRef.value
  if (!root) return

  summaryMermaidDiagrams.value.forEach((diagram, index) => {
    const container = root.querySelector<HTMLElement>(`[data-summary-mermaid-index="${index}"]`)
    const canvas = root.querySelector<HTMLElement>(`[data-summary-mermaid-canvas="${index}"]`)
    if (!container || !canvas) return

    if (diagram.svg) {
      canvas.innerHTML = diagram.svg
      container.dataset.summaryMermaidState = 'ready'
    } else if (diagram.error) {
      canvas.innerHTML = renderMermaidError(diagram.source, diagram.error)
      container.dataset.summaryMermaidState = 'error'
    }
  })
}

function cleanupMermaidRenderArtifacts(renderId: string) {
  document.getElementById(`d${renderId}`)?.remove()
  document.getElementById(`i${renderId}`)?.remove()
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
      cleanupMermaidRenderArtifacts(renderId)
      const { svg, bindFunctions } = await mermaid.render(renderId, diagram.source, canvas)
      if (renderRun !== summaryMermaidRenderRun) return
      diagram.svg = svg
      diagram.error = ''
      canvas.innerHTML = svg
      bindFunctions?.(canvas)
      container.dataset.summaryMermaidState = 'ready'
    } catch (error) {
      if (renderRun !== summaryMermaidRenderRun) return
      markMermaidDiagramError(root, diagrams, index, error)
    } finally {
      const renderId = `summary-mermaid-${props.task.id}-${renderRun}-${index}`
      cleanupMermaidRenderArtifacts(renderId)
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

async function loadSummaryPayloadIfNeeded() {
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

async function toggleSummary() {
  summaryExpanded.value = !summaryExpanded.value
  if (!summaryExpanded.value) return
  await loadSummaryPayloadIfNeeded()
}

async function openSummaryViewer() {
  await loadSummaryPayloadIfNeeded()
  summaryViewerVisible.value = true
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
  selectMermaidZoom('fit')
  mermaidViewerVisible.value = true
}

const commitUrl = computed(() => {
  if (!props.task.commit_sha || !props.task.project_url) return null
  return `${props.task.project_url}/-/commit/${props.task.commit_sha}`
})

const hasChanges = computed(() =>
  props.task.additions !== undefined || props.task.deletions !== undefined
)

</script>

<style scoped>
.task-result-panel {
  border-radius: var(--app-card-radius);
}

.panel-heading {
  display: grid;
  gap: 3px;
}

.panel-eyebrow {
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

.result-body {
  display: grid;
  gap: 0;
  min-width: 0;
}

.result-card {
  padding: 16px 0;
  border: 0;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 0;
  background: transparent;
}

.result-card:first-child {
  padding-top: 2px;
}

.result-card:last-child {
  padding-bottom: 2px;
  border-bottom: 0;
}

.result-card--commit {
  background: transparent;
}

.result-card--error {
  margin-bottom: 14px;
  padding: 14px;
  border: 1px solid rgba(208, 48, 80, 0.18);
  border-radius: 6px;
  background: rgba(208, 48, 80, 0.045);
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

/* Execution summary card */
.result-card--summary-text {
  min-width: 0;
  padding-bottom: 16px;
  overflow-anchor: none;
}

.summary-trigger {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
  padding: 10px 12px;
  border: 1px solid rgba(2, 132, 199, 0.14);
  border-radius: 8px;
  background: linear-gradient(135deg, rgba(2, 132, 199, 0.04) 0%, rgba(2, 132, 199, 0.02) 100%);
  font-family: inherit;
  text-align: left;
  cursor: pointer;
  transition: border-color 0.2s, background 0.2s, box-shadow 0.2s;
}

.summary-trigger:hover {
  border-color: rgba(2, 132, 199, 0.28);
  background: linear-gradient(135deg, rgba(2, 132, 199, 0.07) 0%, rgba(2, 132, 199, 0.03) 100%);
  box-shadow: 0 1px 4px rgba(2, 132, 199, 0.08);
}

.summary-trigger:focus-visible {
  outline: 2px solid rgba(2, 132, 199, 0.45);
  outline-offset: 2px;
}

.summary-trigger:disabled {
  cursor: wait;
  opacity: 0.72;
}

.summary-trigger--expanded {
  border-color: rgba(2, 132, 199, 0.22);
  background: rgba(2, 132, 199, 0.04);
  box-shadow: 0 1px 4px rgba(2, 132, 199, 0.06);
}

.summary-trigger__leading {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
  flex: 1;
}

.summary-trigger__icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 32px;
  height: 32px;
  border-radius: 7px;
  background: rgba(2, 132, 199, 0.1);
  flex-shrink: 0;
}

.summary-trigger__icon {
  color: #0284c7;
}

.summary-trigger__text {
  display: grid;
  grid-template-rows: auto 0fr;
  gap: 2px;
  min-width: 0;
  transition: grid-template-rows 0.2s ease;
}

.summary-trigger__text--has-preview {
  grid-template-rows: auto 1fr;
}

.summary-trigger--expanded .summary-trigger__text--has-preview {
  grid-template-rows: auto 0fr;
}

.summary-trigger__title {
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1, #1a1a2e);
  line-height: 1.35;
}

.summary-trigger__preview {
  font-size: 12px;
  font-weight: 400;
  color: var(--n-text-color-3, #8a8f98);
  line-height: 1.45;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-height: 0;
}

.summary-trigger__actions {
  display: flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

.summary-trigger__action-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: 6px;
  color: var(--n-text-color-3, #8a8f98);
  cursor: pointer;
  transition: background 0.15s, color 0.15s;
}

.summary-trigger__action-btn:hover {
  background: rgba(2, 132, 199, 0.1);
  color: #0284c7;
}

.summary-trigger__chevron {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  color: var(--n-text-color-3, #8a8f98);
  transition: transform 0.2s ease, color 0.15s;
}

.summary-trigger__chevron--open {
  transform: rotate(90deg);
  color: #0284c7;
}

.badge-spin-ring {
  display: inline-block;
  width: 14px;
  height: 14px;
  border-radius: 50%;
  border: 2px solid rgba(2, 132, 199, 0.2);
  border-top-color: #0284c7;
  animation: badge-rotate 0.7s linear infinite;
}

.badge-spin-ring--accent {
  border-color: rgba(2, 132, 199, 0.2);
  border-top-color: #0284c7;
}

@keyframes badge-rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.summary-expand-track {
  display: grid;
  grid-template-rows: 0fr;
  transition: grid-template-rows 0.25s ease;
}

.summary-expand-track--open {
  grid-template-rows: 1fr;
  margin-top: 8px;
}

.summary-expand-body {
  overflow: hidden;
  min-height: 0;
}

.summary-content-scrollbar {
  width: 100%;
  max-width: 100%;
  border-radius: 7px;
}

.summary-content-scrollbar :deep(.n-scrollbar-container) {
  overflow-x: hidden;
}

.summary-content {
  min-width: 0;
  max-width: 100%;
  width: 100%;
  box-sizing: border-box;
  padding: 14px 16px;
  font-size: 13px;
  line-height: 1.7;
  color: var(--n-text-color-2);
  overflow-x: hidden;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.summary-content--empty {
  font-style: italic;
  opacity: 0.4;
}

.summary-content--viewer {
  max-width: 1160px;
  margin: 0 auto;
  padding: clamp(28px, 4vw, 46px);
  border: 1px solid rgba(2, 132, 199, 0.12);
  border-radius: 12px;
  background:
    linear-gradient(180deg, rgba(2, 132, 199, 0.025), transparent 160px),
    var(--n-color, #fff);
  box-shadow:
    0 18px 50px rgba(15, 23, 42, 0.08),
    0 2px 8px rgba(15, 23, 42, 0.04);
  font-size: 14px;
  line-height: 1.75;
}

.summary-content-modal__title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.viewer-modal__title-icon {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  border: 1px solid rgba(2, 132, 199, 0.16);
  border-radius: 9px;
  background: linear-gradient(145deg, rgba(2, 132, 199, 0.14), rgba(2, 132, 199, 0.05));
  color: #0284c7;
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}

.summary-content-modal__viewport {
  flex: 1 1 auto;
  height: 0;
  min-height: 0;
  background:
    radial-gradient(circle at 50% 0, rgba(2, 132, 199, 0.055), transparent 36%),
    rgba(148, 163, 184, 0.035);
}

.summary-mermaid-modal__title {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  font-size: 16px;
  font-weight: 600;
  letter-spacing: -0.01em;
}

.summary-mermaid-modal__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  min-width: 0;
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
  overflow-wrap: anywhere;
  word-break: break-word;
}
.summary-content :deep(pre.md-code-block) {
  margin: 0.5em 0; padding: 10px 12px;
  background: rgba(0, 0, 0, 0.06); border-radius: 5px;
  font-family: var(--n-font-family-mono, monospace);
  max-width: 100%; box-sizing: border-box;
  font-size: 0.85em; line-height: 1.55; white-space: pre-wrap;
  overflow-wrap: anywhere; word-break: break-word;
}
.summary-content :deep(pre.md-code-block code) { background: none; padding: 0; border-radius: 0; font-size: inherit; color: inherit; }
.summary-content :deep(a) { color: var(--n-primary-color, #18a058); text-decoration: none; }
.summary-content :deep(a:hover) { text-decoration: underline; }
.summary-content :deep(img) { max-width: 100%; height: auto; }
.summary-content :deep(table) {
  width: 100%;
  max-width: 100%;
  table-layout: fixed;
  border-collapse: collapse;
}
.summary-content :deep(th),
.summary-content :deep(td) {
  overflow-wrap: anywhere;
  word-break: break-word;
}
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
  overflow-x: hidden;
  overflow-y: auto;
  color: var(--n-text-color-2);
}

.summary-content :deep(.summary-mermaid__canvas svg) {
  display: block;
  width: 100%;
  max-width: 100%;
  height: auto;
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
  overflow: hidden;
  border: 1px solid rgba(2, 132, 199, 0.14);
  border-radius: 14px;
  background: var(--n-color-modal, var(--n-color, #fff));
  box-shadow:
    0 32px 80px rgba(15, 23, 42, 0.22),
    0 8px 24px rgba(15, 23, 42, 0.1);
}

:global(.summary-content-modal) {
  display: flex;
  flex-direction: column;
  max-width: none;
  overflow: hidden;
  border: 1px solid rgba(2, 132, 199, 0.14);
  border-radius: 14px;
  background: var(--n-color-modal, var(--n-color, #fff));
  box-shadow:
    0 32px 80px rgba(15, 23, 42, 0.22),
    0 8px 24px rgba(15, 23, 42, 0.1);
}

:global(.summary-content-modal .n-card-header) {
  flex: 0 0 auto;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  background:
    linear-gradient(90deg, rgba(2, 132, 199, 0.06), transparent 38%),
    var(--n-color-modal, var(--n-color, #fff));
}

:global(.summary-content-modal .n-card-content) {
  display: flex;
  flex: 1 1 auto;
  min-height: 0;
  padding: 0;
  overflow: hidden;
}

:global(.summary-mermaid-modal .n-card-header) {
  flex: 0 0 auto;
  padding: 16px 20px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  background:
    linear-gradient(90deg, rgba(2, 132, 199, 0.06), transparent 32%),
    var(--n-color-modal, var(--n-color, #fff));
}

:global(.summary-mermaid-modal .n-card-header__main) {
  width: 100%;
  min-width: 0;
}

:global(.summary-mermaid-modal .n-card-content) {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
  overflow: hidden;
  padding: 18px;
}

:global(.summary-mermaid-modal__toolbar) {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  min-width: 0;
  padding: 0;
}

:global(.summary-mermaid-modal__zoom-group) {
  display: inline-flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 4px;
  padding: 4px;
  border: 1px solid rgba(2, 132, 199, 0.12);
  border-radius: 10px;
  background: rgba(2, 132, 199, 0.045);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.5);
}

:global(.summary-mermaid-modal__zoom-group .n-button) {
  min-width: 44px;
  border-radius: 7px;
}

:global(.summary-mermaid-modal__custom-zoom) {
  display: flex;
  width: 64px;
}

:global(.summary-mermaid-modal__viewport) {
  flex: 1 1 auto;
  height: 0;
  min-height: 0;
  border: 1px solid var(--n-border-color, rgba(128, 128, 128, 0.18));
  border-radius: 10px;
  background-color: var(--n-color, #fff);
  background-image:
    linear-gradient(rgba(2, 132, 199, 0.055) 1px, transparent 1px),
    linear-gradient(90deg, rgba(2, 132, 199, 0.055) 1px, transparent 1px),
    radial-gradient(circle at 50% 45%, rgba(2, 132, 199, 0.055), transparent 42%);
  background-size: 24px 24px, 24px 24px, 100% 100%;
  background-position: -1px -1px, -1px -1px, 0 0;
  box-shadow:
    inset 0 1px 0 rgba(255, 255, 255, 0.55),
    0 10px 28px rgba(15, 23, 42, 0.08);
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
  display: grid;
  place-items: center;
  min-width: 0;
  min-height: 100%;
}

:global(.summary-mermaid-modal__canvas svg) {
  display: block;
  height: auto;
  max-width: none;
}

:global(.summary-mermaid-modal__canvas--fit svg) {
  max-width: 100%;
}

@media (hover: hover) and (pointer: fine) {
  :global(.summary-mermaid-modal__zoom-group .n-button:hover) {
    transform: translateY(-1px);
  }
}

@media (max-width: 640px) {
  .summary-content--viewer {
    padding: 24px 18px;
    border-radius: 10px;
  }

  :global(.summary-content-modal),
  :global(.summary-mermaid-modal) {
    border-radius: 10px;
  }

  :global(.summary-content-modal .n-card-header),
  :global(.summary-mermaid-modal .n-card-header) {
    padding: 14px;
  }

  :global(.summary-mermaid-modal .n-card-content) {
    padding: 10px;
  }

  .summary-mermaid-modal__header {
    align-items: flex-start;
    flex-direction: column;
    gap: 10px;
  }

  :global(.summary-mermaid-modal__toolbar) {
    justify-content: flex-start;
    width: 100%;
    padding: 0;
  }
}
</style>
