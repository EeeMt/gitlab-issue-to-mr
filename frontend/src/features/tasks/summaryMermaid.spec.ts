import { describe, expect, it, vi } from 'vitest'

import {
  applyMermaidViewerSvgStyle,
  renderSummaryMarkdownWithMermaid,
  renderSummaryMermaidError,
} from './summaryMermaid'

const labels = {
  copySource: 'Copy source',
  openLarge: 'Open large',
  loading: 'Loading',
}

describe('summary Mermaid rendering contract', () => {
  it('extracts Mermaid fences while preserving surrounding Markdown', () => {
    const renderMarkdown = vi.fn((value: string) => `<md>${value}</md>`)
    const result = renderSummaryMarkdownWithMermaid(
      'Before\n```mermaid\ngraph TD\nA-->B\n```\nAfter',
      renderMarkdown,
      labels,
    )

    expect(result.diagrams).toEqual([
      { source: 'graph TD\nA-->B', svg: '', error: '' }
    ])
    expect(result.html).toContain('<md>Before\n</md>')
    expect(result.html).toContain('data-summary-mermaid-index="0"')
    expect(result.html).toContain('<md>\nAfter</md>')
  })

  it('escapes diagram source and error details', () => {
    const html = renderSummaryMermaidError(
      '<script>alert(1)</script>',
      new Error('<broken>'),
      'Render failed',
    )

    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
    expect(html).toContain('&lt;broken&gt;')
  })

  it('applies viewer sizing without discarding existing SVG styles', () => {
    expect(applyMermaidViewerSvgStyle(
      '<svg style="color: red"></svg>',
      '150%',
    )).toContain('color: red width: 150%')
  })
})
