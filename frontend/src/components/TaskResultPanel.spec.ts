import { describe, expect, it } from 'vitest'
import taskResultPanelSource from './TaskResultPanel.vue?raw'
import taskRunMetricsSource from './TaskRunMetrics.vue?raw'
import taskContinuationPanelSource from './TaskContinuationPanel.vue?raw'
import summaryMermaidSource from '../features/tasks/summaryMermaid.ts?raw'
import summaryMermaidViewerSource from '../features/tasks/useSummaryMermaidViewer.ts?raw'
import summaryCollapseFloatSource from '../features/tasks/useSummaryCollapseFloat.ts?raw'
import summaryRendererSource from '../features/tasks/useSummaryRenderer.ts?raw'
import deliverySummaryPayloadSource from '../features/tasks/useDeliverySummaryPayload.ts?raw'
import summaryCopyActionsSource from '../features/tasks/useSummaryCopyActions.ts?raw'

function cssBlock(selector: string): string {
  const start = taskResultPanelSource.indexOf(`${selector} {`)
  expect(start).toBeGreaterThanOrEqual(0)
  const end = taskResultPanelSource.indexOf('}', start)
  expect(end).toBeGreaterThan(start)
  return taskResultPanelSource.slice(start, end + 1)
}

describe('TaskResultPanel', () => {
  it('uses a lighter tabular UI font for change line numbers', () => {
    const commitStats = cssBlock('.commit-stats')

    expect(commitStats).toContain('font-family: var(--n-font-family-mono, monospace);')
    expect(commitStats).toContain('font-variant-numeric: tabular-nums;')
  })

  it('execution summary card is guarded by selectedSummaryLog and uses result-card--summary-text class', () => {
    expect(taskResultPanelSource).toContain('v-if="selectedSummaryLog"')
    expect(deliverySummaryPayloadSource).toContain(
      'options.deliverySummaryLog.value ?? options.lastAssistantLog.value ?? null'
    )
    expect(taskResultPanelSource).toContain('result-card--summary-text')
    // Both must appear together on the same element
    const summaryCardIndex = taskResultPanelSource.indexOf('result-card--summary-text')
    const nearbySource = taskResultPanelSource.slice(Math.max(0, summaryCardIndex - 60), summaryCardIndex + 60)
    expect(nearbySource).toContain('selectedSummaryLog')
  })

  it('summary panel starts collapsed (summaryExpanded initialised to ref(false))', () => {
    expect(taskResultPanelSource).toContain('const summaryExpanded = ref(false)')
  })

  it('summary header exposes the full row as an expandable button', () => {
    expect(taskResultPanelSource).toContain('class="summary-trigger"')
    expect(taskResultPanelSource).toContain(':aria-expanded="summaryExpanded"')
    expect(taskResultPanelSource).toContain('taskView.summaryCollapse')
  })

  it('opens the complete delivery summary in a large mixed-content viewer', () => {
    expect(taskResultPanelSource).toContain('class="summary-trigger__action-btn"')
    expect(taskResultPanelSource).toContain(':aria-label="t(\'taskView.summaryOpenLarge\')"')
    expect(taskResultPanelSource).toContain('openSummaryViewer')
    expect(taskResultPanelSource).toContain('class="summary-content-modal"')
    expect(taskResultPanelSource).toContain('ref="summaryViewerContentRef"')
    expect(summaryRendererSource).toContain('function hydrateSummaryViewerMermaid()')
    expect(summaryRendererSource).toContain('canvas.innerHTML = diagram.svg')
    expect(taskResultPanelSource).toContain("width: 'min(1320px, calc(100vw - 32px))'")
  })

  it('copies the complete raw delivery summary from the card and large viewer', () => {
    expect(taskResultPanelSource.match(/@click(?:\.stop)?="copySummarySource"/g)).toHaveLength(2)
    expect(summaryCopyActionsSource).toContain('async function copySummarySource()')
    expect(summaryCopyActionsSource).toContain(
      'const payloadAvailable = await options.loadSummaryPayloadIfNeeded()'
    )
    expect(summaryCopyActionsSource).toContain('await copySource(options.summaryText.value)')
    expect(summaryCopyActionsSource).toContain('await navigator.clipboard.writeText(source)')
    expect(summaryCopyActionsSource).toContain("message.success(t('taskView.copied'))")
    expect(summaryCopyActionsSource).toContain('summaryCopied.value = true')
    expect(taskResultPanelSource).toContain('summaryCopied ? Checkmark : CopyOutline')
  })

  it('keeps the large summary viewer copy action visually quiet until interaction', () => {
    const copyButtonStart = taskResultPanelSource.indexOf('class="summary-content-modal__copy"')
    const copyButtonEnd = taskResultPanelSource.indexOf('</n-button>', copyButtonStart)
    const copyButton = taskResultPanelSource.slice(copyButtonStart, copyButtonEnd)

    expect(copyButton).toContain('quaternary')
    expect(copyButton).not.toContain('secondary')
  })

  it('copies the original Mermaid source from every diagram card', () => {
    expect(summaryMermaidSource).toContain('data-summary-mermaid-action="copy"')
    expect(summaryCopyActionsSource).toContain('const diagram = options.diagrams.value[index]')
    expect(summaryCopyActionsSource).toContain('void copySource(diagram.source)')
    expect(summaryCopyActionsSource).toContain("button.textContent = t('taskView.copied')")
  })

  it('presents the full delivery summary as a focused document reader', () => {
    const summaryModal = cssBlock(':global(.summary-content-modal)')
    const summaryModalHeader = cssBlock(':global(.summary-content-modal .n-card-header)')
    const summaryViewer = cssBlock('.summary-content--viewer')
    const summaryTitleIcon = cssBlock('.viewer-modal__title-icon')

    expect(taskResultPanelSource).toContain('summary-content-modal__title-icon')
    expect(summaryModal).toContain('border-radius: 14px;')
    expect(summaryModal).toContain('overflow: hidden;')
    expect(summaryModal).toContain('box-shadow:')
    expect(summaryModalHeader).toContain('background:')
    expect(summaryViewer).toContain('border: 1px solid')
    expect(summaryViewer).toContain('border-radius: 12px;')
    expect(summaryViewer).toContain('max-width: 1160px;')
    expect(summaryViewer).toContain('box-shadow:')
    expect(summaryTitleIcon).toContain('background:')
  })

  it('shows a floating collapse action while the summary is expanded', () => {
    const collapseFloat = cssBlock('.summary-collapse-float')
    const collapseFooter = cssBlock('.summary-collapse-footer')
    const collapseButtonIcon = cssBlock('.summary-collapse-button__icon')

    expect(taskResultPanelSource).toContain('v-if="summaryExpanded && !mermaidViewerVisible && !summaryViewerVisible"')
    expect(taskResultPanelSource).toContain('class="summary-collapse-button"')
    expect(taskResultPanelSource).toContain('class="summary-collapse-footer"')
    expect(taskResultPanelSource).toContain(':style="summaryCollapseFloatStyle"')
    expect(taskResultPanelSource).toContain('ref="summaryCardRef"')
    expect(summaryCollapseFloatSource).toContain('function update()')
    expect(summaryCollapseFloatSource).toContain('rect.bottom <= window.innerHeight + 160')
    expect(taskResultPanelSource).toContain('@click="toggleSummary"')
    expect(taskResultPanelSource).toContain("{{ t('taskView.summaryCollapse') }}")
    expect(collapseFloat).toContain('position: fixed;')
    expect(collapseFloat).not.toContain('left: 50%;')
    expect(collapseFloat).toContain('justify-content: center;')
    expect(collapseFloat).toContain('transform: translate(-50%, -100%);')
    expect(collapseFloat).toContain('pointer-events: none;')
    expect(collapseFooter).toContain('display: flex;')
    expect(collapseFooter).toContain('justify-content: center;')
    expect(collapseButtonIcon).toContain('transform: rotate(-90deg);')
  })

  it('keeps the collapsed summary row from forcing horizontal overflow', () => {
    const resultBody = cssBlock('.result-body')
    const summaryCard = cssBlock('.result-card--summary-text')
    const summaryTrigger = cssBlock('.summary-trigger')
    const summaryPreview = cssBlock('.summary-trigger__preview')

    expect(resultBody).toContain('min-width: 0;')
    expect(summaryCard).toContain('min-width: 0;')
    expect(summaryTrigger).toContain('box-sizing: border-box;')
    expect(summaryTrigger).toContain('width: 100%;')
    expect(summaryPreview).toContain('min-width: 0;')
    expect(summaryPreview).toContain('max-width: 100%;')
    expect(summaryPreview).toContain('text-overflow: ellipsis;')
    expect(summaryPreview).toContain('white-space: nowrap;')
  })

  it('moves run statistics into the dedicated sidebar component', () => {
    expect(taskResultPanelSource).not.toContain('v-if="contextCompactCount != null"')
    expect(taskRunMetricsSource).toContain('v-if="contextCompactCount != null"')
    expect(taskRunMetricsSource).toContain('taskView.runStatistics')
  })

  it('renders skill usage stats in the dedicated run statistics component', () => {
    expect(taskRunMetricsSource).toContain('skillUsageStats?: SkillUsageStat[]')
    expect(taskRunMetricsSource).toContain('taskView.skillUsage')
    expect(taskRunMetricsSource).toContain('skillUsageStats.length > 0')
  })

  it('keeps input and output token counts inside the metrics grid', () => {
    const metricsGridStart = taskRunMetricsSource.indexOf('<div class="metrics-grid">')
    const metricsGridEnd = taskRunMetricsSource.indexOf('</div>\n\n    <div v-if="skillUsageStats.length', metricsGridStart)
    const metricsGridSource = taskRunMetricsSource.slice(metricsGridStart, metricsGridEnd)

    expect(metricsGridSource).toContain("t('taskView.inputTokens')")
    expect(metricsGridSource).toContain("t('taskView.outputTokens')")
    expect(taskRunMetricsSource).not.toContain("t('taskView.tokenBreakdown'")
  })

  it('keeps issue continuation in a dedicated sidebar component', () => {
    expect(taskResultPanelSource).not.toContain('canAppendFollowupTask?: boolean')
    expect(taskContinuationPanelSource).toContain('canAppendFollowupTask?: boolean')
    expect(taskContinuationPanelSource).toContain("(event: 'append-followup-task'): void")
    expect(taskContinuationPanelSource).toContain("canAppendFollowupTask ? t('taskView.appendFollowupTitle') : t('taskView.continueGuideTitle')")
    expect(taskContinuationPanelSource).toContain('v-if="canAppendFollowupTask"')
    expect(taskContinuationPanelSource).toContain("@click=\"emit('append-followup-task')\"")
    expect(taskContinuationPanelSource).toContain('@click="goToIssue"')
  })

  it('adds Mermaid rendering only to the AI delivery summary panel', () => {
    expect(summaryRendererSource).toContain("await import('mermaid')")
    expect(summaryRendererSource).not.toContain("import mermaid from 'mermaid'")
    expect(summaryMermaidSource).toContain('function renderSummaryMarkdownWithMermaid(')
    expect(summaryMermaidSource).toContain('[ \\t]*mermaid')
    expect(summaryRendererSource).toContain('const generation = ++renderGeneration')
    expect(summaryRendererSource).toContain('renderSummaryMarkdownWithMermaid(text, renderMarkdown')
    expect(summaryRendererSource).toContain('summaryRenderedHtml.value = rendered.html')
    expect(summaryRendererSource).toContain('if (options.diagrams.value.length > 0)')
    expect(summaryRendererSource).toContain('renderSummaryMermaidDiagrams(generation)')
    expect(summaryMermaidSource).toContain('renderMarkdown(before)')
    expect(summaryMermaidSource).toContain('renderMarkdown(after)')
  })

  it('handles stale and failed Mermaid render attempts without leaving loading placeholders', () => {
    expect(summaryRendererSource).toContain('function markMermaidDiagramError(')
    expect(summaryRendererSource).toContain('markMermaidDiagramError(root, diagrams, index, error)')
    expect(summaryRendererSource).toContain('if (generation !== renderGeneration) return')
    expect(summaryRendererSource).toContain('options.resetMermaidViewer()')
  })

  it('keeps Mermaid temporary render artifacts inside the summary canvas', () => {
    expect(summaryRendererSource).toContain('function cleanupMermaidRenderArtifacts(renderId: string)')
    expect(summaryRendererSource).toContain('document.getElementById(`d${renderId}`)?.remove()')
    expect(summaryRendererSource).toContain('document.getElementById(`i${renderId}`)?.remove()')
    expect(summaryRendererSource).toContain('const { svg, bindFunctions } = await mermaid.render(')
    expect(summaryRendererSource).toContain('cleanupMermaidRenderArtifacts(renderId)')
  })

  it('provides a larger Mermaid diagram viewer for summary diagrams', () => {
    const mermaidViewerSvg = cssBlock(':global(.summary-mermaid-modal__canvas svg)')
    const mermaidModalHeader = cssBlock(':global(.summary-mermaid-modal .n-card-header)')
    const mermaidModalContent = cssBlock(':global(.summary-mermaid-modal .n-card-content)')
    const mermaidModalViewport = cssBlock(':global(.summary-mermaid-modal__viewport)')
    const mermaidModalViewportDragging = cssBlock(':global(.summary-mermaid-modal__viewport--dragging)')
    const mermaidModalToolbar = cssBlock(':global(.summary-mermaid-modal__toolbar)')
    const mermaidZoomGroup = cssBlock(':global(.summary-mermaid-modal__zoom-group)')
    const mermaidCustomZoom = cssBlock(':global(.summary-mermaid-modal__custom-zoom)')
    const mermaidCanvas = cssBlock(':global(.summary-mermaid-modal__canvas)')
    const mermaidModalScrollbarContainer = cssBlock(':global(.summary-mermaid-modal__viewport .n-scrollbar-container)')

    expect(taskResultPanelSource).toContain('summary-mermaid-modal')
    expect(taskResultPanelSource).toContain('mermaidViewerVisible')
    expect(taskResultPanelSource).toContain('mermaidZoomOptions')
    expect(summaryRendererSource).toContain('taskView.mermaidOpenLarge')
    expect(taskResultPanelSource).toContain("height: 'calc(100vh - 32px)'")
    expect(taskResultPanelSource).toContain("width: 'calc(100vw - 32px)'")
    expect(taskResultPanelSource).not.toContain("{ value: '400', label: '400%' }")
    expect(summaryMermaidViewerSource).toContain('const mermaidCustomZoom = ref(100)')
    expect(summaryMermaidViewerSource).toContain('const mermaidZoomPercent = computed')
    expect(summaryMermaidViewerSource).toContain('Math.min(100, mermaidZoomPercent.value)')
    expect(summaryMermaidViewerSource).toContain('Math.max(100, mermaidZoomPercent.value)')
    expect(summaryMermaidViewerSource).toContain('width: `${contentZoom}%`')
    expect(taskResultPanelSource).toContain('<n-input-number')
    expect(taskResultPanelSource).toContain(':min="mermaidZoomMin"')
    expect(taskResultPanelSource).toContain(':max="mermaidZoomMax"')
    expect(taskResultPanelSource).toContain(':step="10"')
    expect(taskResultPanelSource).toContain('<template #suffix>%</template>')
    expect(summaryMermaidViewerSource).toContain("applyMermaidViewerSvgStyle(activeMermaidRawSvg.value, '100%')")
    expect(taskResultPanelSource).toContain(':style="mermaidViewerCanvasStyle"')
    expect(summaryMermaidViewerSource).toContain('const mermaidViewerCanvasStyle = computed<CSSProperties>')
    expect(taskResultPanelSource).toContain(':content-style="mermaidViewerContentStyle"')
    expect(summaryMermaidViewerSource).toContain('const mermaidViewerContentStyle = computed<CSSProperties>')
    expect(summaryMermaidSource).toContain('width: ${width}; height: auto; max-width: none; display: block;')
    expect(summaryMermaidSource).toContain('style="$1 ${viewerStyle}"')
    expect(taskResultPanelSource).toContain(':key="mermaidViewerScrollbarKey"')
    expect(summaryMermaidViewerSource).toContain('const mermaidViewerScrollbarKey = computed')
    expect(taskResultPanelSource).toContain('@mousedown="handleMermaidViewerMouseDown"')
    expect(taskResultPanelSource).toContain('@wheel.prevent="handleMermaidViewerWheel"')
    expect(summaryMermaidViewerSource).toContain('function handleMermaidViewerMouseMove(event: MouseEvent)')
    expect(summaryMermaidViewerSource).toContain('container.scrollLeft = mermaidViewerDrag.scrollLeft - deltaX')
    expect(summaryMermaidViewerSource).toContain('container.scrollTop = mermaidViewerDrag.scrollTop - deltaY')
    expect(summaryMermaidViewerSource).toContain("viewport?.querySelector<HTMLElement>('.n-scrollbar-container')")
    expect(summaryMermaidViewerSource).toContain("window.removeEventListener('mousemove', handleMermaidViewerMouseMove)")
    expect(taskResultPanelSource).toContain('class="summary-mermaid-modal__title"')
    expect(taskResultPanelSource).toContain('class="summary-mermaid-modal__zoom-group"')
    expect(mermaidModalHeader).toContain('flex: 0 0 auto;')
    expect(mermaidModalHeader).toContain('border-bottom:')
    expect(mermaidModalContent).toContain('overflow: hidden;')
    expect(mermaidModalContent).toContain('padding: 18px;')
    expect(mermaidModalContent).not.toContain('height: 100%;')
    expect(mermaidModalToolbar).toContain('justify-content: flex-end;')
    expect(mermaidModalToolbar).toContain('padding: 0;')
    expect(mermaidZoomGroup).toContain('align-items: center;')
    expect(mermaidCustomZoom).toContain('display: flex;')
    expect(mermaidCustomZoom).toContain('width: 64px;')
    expect(mermaidCanvas).toContain('min-width: 0;')
    expect(mermaidModalViewport).toContain('flex: 1 1 auto;')
    expect(mermaidModalViewport).toContain('height: 0;')
    expect(mermaidModalViewport).toContain('border-radius: 10px;')
    expect(mermaidModalViewport).toContain('background-image:')
    expect(mermaidModalViewport).toContain('cursor: grab;')
    expect(mermaidModalViewport).toContain('user-select: none;')
    expect(mermaidModalViewportDragging).toContain('cursor: grabbing;')
    expect(mermaidModalScrollbarContainer).toContain('max-height: 100%;')
    expect(mermaidViewerSvg).not.toContain('width: var(--summary-mermaid-viewer-width')
  })

  it('keeps Mermaid zoom controls inside the modal header', () => {
    const modalStart = taskResultPanelSource.indexOf('class="summary-mermaid-modal"')
    const headerStart = taskResultPanelSource.indexOf('<template #header>', modalStart)
    const headerEnd = taskResultPanelSource.indexOf('</template>', headerStart)
    const toolbarIndex = taskResultPanelSource.indexOf(
      'class="summary-mermaid-modal__toolbar"',
      modalStart
    )

    expect(modalStart).toBeGreaterThanOrEqual(0)
    expect(headerStart).toBeGreaterThan(modalStart)
    expect(toolbarIndex).toBeGreaterThan(headerStart)
    expect(toolbarIndex).toBeLessThan(headerEnd)
  })

  it('keeps wheel, preset, and custom Mermaid zoom values synchronized', () => {
    expect(summaryMermaidViewerSource).toContain('const mermaidZoomMin = 10')
    expect(summaryMermaidViewerSource).toContain('const mermaidZoomMax = 2000')
    expect(taskResultPanelSource).toContain('@click="selectMermaidZoom(option.value)"')
    expect(summaryMermaidViewerSource).toContain('function selectMermaidZoom(value: MermaidZoom)')
    expect(summaryMermaidViewerSource).toContain('function clampMermaidZoom(value: number)')
    expect(summaryMermaidViewerSource).toContain('function handleMermaidViewerWheel(event: WheelEvent)')
    expect(summaryMermaidViewerSource).toContain("mermaidZoom.value = 'custom'")
    expect(summaryMermaidViewerSource).toContain('mermaidCustomZoom.value = nextZoom')
    expect(summaryMermaidViewerSource).toContain('const zoomRatio = nextZoom / currentZoom')
    expect(summaryMermaidViewerSource).toContain('nextContainer.scrollLeft =')
    expect(summaryMermaidViewerSource).toContain('nextContainer.scrollTop =')
  })

  it('keeps the Mermaid viewer from changing the page scrollbar gutter', () => {
    const mermaidModalIndex = taskResultPanelSource.indexOf('class="summary-mermaid-modal"')
    expect(mermaidModalIndex).toBeGreaterThanOrEqual(0)

    const nearbySource = taskResultPanelSource.slice(
      Math.max(0, mermaidModalIndex - 120),
      mermaidModalIndex + 180
    )
    expect(nearbySource).toContain(':block-scroll="false"')
  })

  it('keeps summary readers free of horizontal scrolling while preserving Mermaid zoom panning', () => {
    const summaryContentScrollbar = cssBlock('.summary-content-scrollbar')
    const summaryContent = cssBlock('.summary-content')
    const summaryCodeBlock = cssBlock('.summary-content :deep(pre.md-code-block)')
    const summaryMermaidCanvas = cssBlock('.summary-content :deep(.summary-mermaid__canvas)')
    const summaryMermaidSvg = cssBlock('.summary-content :deep(.summary-mermaid__canvas svg)')
    const mermaidModalViewport = cssBlock(':global(.summary-mermaid-modal__viewport)')
    const horizontalScrollbarCount = taskResultPanelSource.match(/\bx-scrollable\b/g)?.length ?? 0

    expect(taskResultPanelSource).toContain('NScrollbar')
    expect(taskResultPanelSource).toContain('class="summary-content-scrollbar"')
    expect(taskResultPanelSource).toContain('content-style="min-width: 100%;"')
    expect(taskResultPanelSource).toContain('class="summary-mermaid-modal__viewport"')
    expect(horizontalScrollbarCount).toBe(1)
    expect(taskResultPanelSource).toContain('trigger="none"')
    expect(summaryContentScrollbar).toContain('width: 100%;')
    expect(summaryContent).toContain('width: 100%;')
    expect(summaryContent).toContain('box-sizing: border-box;')
    expect(summaryContent).toContain('overflow-wrap: anywhere;')
    expect(summaryCodeBlock).toContain('white-space: pre-wrap;')
    expect(summaryCodeBlock).toContain('overflow-wrap: anywhere;')
    expect(summaryMermaidCanvas).toContain('max-height: 60vh;')
    expect(summaryMermaidCanvas).toContain('overflow-x: hidden;')
    expect(summaryMermaidCanvas).toContain('overflow-y: auto;')
    expect(summaryMermaidSvg).toContain('width: 100%;')
    expect(summaryMermaidSvg).toContain('max-width: 100%;')
    expect(summaryMermaidSvg).toContain('height: auto;')
    expect(mermaidModalViewport).toContain('height: 0;')
  })
})
