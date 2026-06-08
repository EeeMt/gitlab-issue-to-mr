import { describe, expect, it } from 'vitest'
import taskResultPanelSource from './TaskResultPanel.vue?raw'

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

  it('execution summary card is guarded by v-if="lastAssistantLog" and uses result-card--summary-text class', () => {
    expect(taskResultPanelSource).toContain('v-if="lastAssistantLog"')
    expect(taskResultPanelSource).toContain('result-card--summary-text')
    // Both must appear together on the same element
    const summaryCardIndex = taskResultPanelSource.indexOf('result-card--summary-text')
    const nearbySource = taskResultPanelSource.slice(Math.max(0, summaryCardIndex - 60), summaryCardIndex + 60)
    expect(nearbySource).toContain('lastAssistantLog')
  })

  it('summary panel starts collapsed (summaryExpanded initialised to ref(false))', () => {
    expect(taskResultPanelSource).toContain('const summaryExpanded = ref(false)')
  })

  it('summary header exposes the full row as an expandable button', () => {
    expect(taskResultPanelSource).toContain('class="result-card__title summary-header-button"')
    expect(taskResultPanelSource).toContain(':aria-expanded="summaryExpanded"')
    expect(taskResultPanelSource).toContain('taskView.summaryExpand')
    expect(taskResultPanelSource).toContain('taskView.summaryCollapse')
  })

  it('shows a floating collapse action while the summary is expanded', () => {
    const collapseFloat = cssBlock('.summary-collapse-float')
    const collapseFooter = cssBlock('.summary-collapse-footer')
    const collapseButtonIcon = cssBlock('.summary-collapse-button__icon')

    expect(taskResultPanelSource).toContain('v-if="summaryExpanded && !mermaidViewerVisible"')
    expect(taskResultPanelSource).toContain('class="summary-collapse-button"')
    expect(taskResultPanelSource).toContain('class="summary-collapse-footer"')
    expect(taskResultPanelSource).toContain(':style="summaryCollapseFloatStyle"')
    expect(taskResultPanelSource).toContain('ref="summaryCardRef"')
    expect(taskResultPanelSource).toContain('function updateSummaryCollapseFloat()')
    expect(taskResultPanelSource).toContain('summaryCollapseFloatEndThreshold')
    expect(taskResultPanelSource).toContain('rect.bottom <= window.innerHeight + summaryCollapseFloatEndThreshold')
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
    const summaryHeaderButton = cssBlock('.summary-header-button')
    const summaryPreview = cssBlock('.summary-preview')

    expect(resultBody).toContain('min-width: 0;')
    expect(summaryCard).toContain('min-width: 0;')
    expect(summaryHeaderButton).toContain('min-width: 0;')
    expect(summaryHeaderButton).toContain('box-sizing: border-box;')
    expect(summaryPreview).toContain('min-width: 0;')
    expect(summaryPreview).toContain('max-width: 100%;')
    expect(summaryPreview).toContain('text-overflow: ellipsis;')
    expect(summaryPreview).toContain('white-space: nowrap;')
  })

  it('context compact count item is guarded by v-if="contextCompactCount != null"', () => {
    expect(taskResultPanelSource).toContain('v-if="contextCompactCount != null"')
  })

  it('renders skill usage stats in the run statistics card', () => {
    expect(taskResultPanelSource).toContain('skillUsageStats?: SkillUsageStat[]')
    expect(taskResultPanelSource).toContain('taskView.skillUsage')
    expect(taskResultPanelSource).toContain('skillUsageStats.length > 0')
  })

  it('adds Mermaid rendering only to the AI delivery summary panel', () => {
    expect(taskResultPanelSource).toContain("await import('mermaid')")
    expect(taskResultPanelSource).not.toContain("import mermaid from 'mermaid'")
    expect(taskResultPanelSource).toContain('function renderSummaryMarkdown(text: string): string')
    expect(taskResultPanelSource).toContain('[ \\t]*mermaid')
    expect(taskResultPanelSource).toContain('const renderRun = ++summaryMermaidRenderRun')
    expect(taskResultPanelSource).toContain('summaryRenderedHtml.value = renderSummaryMarkdown(text)')
    expect(taskResultPanelSource).toContain('if (summaryMermaidDiagrams.value.length === 0) return')
    expect(taskResultPanelSource).toContain('renderSummaryMermaidDiagrams(renderRun)')
    expect(taskResultPanelSource).toContain('renderMarkdown(before)')
    expect(taskResultPanelSource).toContain('renderMarkdown(after)')
  })

  it('handles stale and failed Mermaid render attempts without leaving loading placeholders', () => {
    expect(taskResultPanelSource).toContain('function markMermaidDiagramError(')
    expect(taskResultPanelSource).toContain('diagrams.forEach((_, index) => markMermaidDiagramError(root, diagrams, index, error))')
    expect(taskResultPanelSource).toContain('if (renderRun !== summaryMermaidRenderRun) return')
    expect(taskResultPanelSource).toContain('resetMermaidViewer()')
  })

  it('provides a larger Mermaid diagram viewer for summary diagrams', () => {
    const mermaidViewerSvg = cssBlock(':global(.summary-mermaid-modal__canvas svg)')
    const mermaidModalHeader = cssBlock(':global(.summary-mermaid-modal .n-card-header)')
    const mermaidModalContent = cssBlock(':global(.summary-mermaid-modal .n-card-content)')
    const mermaidModalViewport = cssBlock(':global(.summary-mermaid-modal__viewport)')
    const mermaidModalViewportDragging = cssBlock(':global(.summary-mermaid-modal__viewport--dragging)')
    const mermaidModalToolbar = cssBlock(':global(.summary-mermaid-modal__toolbar)')
    const mermaidModalScrollbarContainer = cssBlock(':global(.summary-mermaid-modal__viewport .n-scrollbar-container)')

    expect(taskResultPanelSource).toContain('summary-mermaid-modal')
    expect(taskResultPanelSource).toContain('mermaidViewerVisible')
    expect(taskResultPanelSource).toContain('mermaidZoomOptions')
    expect(taskResultPanelSource).toContain('taskView.mermaidOpenLarge')
    expect(taskResultPanelSource).toContain("height: 'calc(100vh - 32px)'")
    expect(taskResultPanelSource).toContain("width: 'calc(100vw - 32px)'")
    expect(taskResultPanelSource).toContain("{ value: '400', label: '400%' }")
    expect(taskResultPanelSource).toContain('applyMermaidViewerSvgStyle(activeMermaidRawSvg.value, mermaidViewerSvgWidth.value)')
    expect(taskResultPanelSource).toContain(':style="mermaidViewerCanvasStyle"')
    expect(taskResultPanelSource).toContain('const mermaidViewerCanvasStyle = computed<CSSProperties>')
    expect(taskResultPanelSource).toContain(':content-style="mermaidViewerContentStyle"')
    expect(taskResultPanelSource).toContain('const mermaidViewerContentStyle = computed<CSSProperties>')
    expect(taskResultPanelSource).toContain('width: `${mermaidZoom.value}%`')
    expect(taskResultPanelSource).toContain("return '100%'")
    expect(taskResultPanelSource).toContain('width: ${width}; height: auto; max-width: none; display: block;')
    expect(taskResultPanelSource).toContain('style="$1 ${viewerStyle}"')
    expect(taskResultPanelSource).toContain(':key="mermaidViewerScrollbarKey"')
    expect(taskResultPanelSource).toContain('const mermaidViewerScrollbarKey = computed')
    expect(taskResultPanelSource).toContain('@mousedown="handleMermaidViewerMouseDown"')
    expect(taskResultPanelSource).toContain('function handleMermaidViewerMouseMove(event: MouseEvent)')
    expect(taskResultPanelSource).toContain('container.scrollLeft = mermaidViewerDrag.scrollLeft - deltaX')
    expect(taskResultPanelSource).toContain('container.scrollTop = mermaidViewerDrag.scrollTop - deltaY')
    expect(taskResultPanelSource).toContain("viewport?.querySelector<HTMLElement>('.n-scrollbar-container')")
    expect(taskResultPanelSource).toContain("window.removeEventListener('mousemove', handleMermaidViewerMouseMove)")
    expect(mermaidModalHeader).toContain('position: absolute;')
    expect(mermaidModalHeader).toContain('right: 10px;')
    expect(mermaidModalContent).toContain('overflow: hidden;')
    expect(mermaidModalContent).toContain('padding-top: 12px;')
    expect(mermaidModalContent).not.toContain('height: 100%;')
    expect(mermaidModalToolbar).toContain('padding-right: 36px;')
    expect(mermaidModalViewport).toContain('flex: 1 1 auto;')
    expect(mermaidModalViewport).toContain('height: 0;')
    expect(mermaidModalViewport).toContain('cursor: grab;')
    expect(mermaidModalViewport).toContain('user-select: none;')
    expect(mermaidModalViewportDragging).toContain('cursor: grabbing;')
    expect(mermaidModalScrollbarContainer).toContain('max-height: 100%;')
    expect(mermaidViewerSvg).not.toContain('width: var(--summary-mermaid-viewer-width')
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

  it('uses Naive UI scrollbars for summary content and the Mermaid viewer', () => {
    const summaryContentScrollbar = cssBlock('.summary-content-scrollbar')
    const summaryContent = cssBlock('.summary-content')
    const summaryCodeBlock = cssBlock('.summary-content :deep(pre.md-code-block)')
    const summaryMermaidCanvas = cssBlock('.summary-content :deep(.summary-mermaid__canvas)')
    const mermaidModalViewport = cssBlock(':global(.summary-mermaid-modal__viewport)')

    expect(taskResultPanelSource).toContain('NScrollbar')
    expect(taskResultPanelSource).toContain('class="summary-content-scrollbar"')
    expect(taskResultPanelSource).toContain('content-style="min-width: 100%;"')
    expect(taskResultPanelSource).toContain('class="summary-mermaid-modal__viewport"')
    expect(taskResultPanelSource).toContain('x-scrollable')
    expect(taskResultPanelSource).toContain('trigger="none"')
    expect(summaryContentScrollbar).toContain('width: 100%;')
    expect(summaryContent).toContain('width: 100%;')
    expect(summaryContent).toContain('box-sizing: border-box;')
    expect(summaryCodeBlock).not.toContain('overflow-x: auto;')
    expect(summaryMermaidCanvas).toContain('max-height: 60vh;')
    expect(summaryMermaidCanvas).toContain('overflow: auto;')
    expect(mermaidModalViewport).toContain('height: 0;')
  })
})
