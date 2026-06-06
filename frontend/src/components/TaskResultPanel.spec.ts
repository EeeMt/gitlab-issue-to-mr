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
    expect(taskResultPanelSource).toContain('summary-mermaid-modal')
    expect(taskResultPanelSource).toContain('mermaidViewerVisible')
    expect(taskResultPanelSource).toContain('mermaidZoomOptions')
    expect(taskResultPanelSource).toContain('taskView.mermaidOpenLarge')
  })
})
