export interface SummaryMermaidDiagram {
  source: string
  svg: string
  error: string
}

export interface SummaryMermaidLabels {
  copySource: string
  openLarge: string
  loading: string
}

export function applyMermaidViewerSvgStyle(svg: string, width: string): string {
  if (!svg) return ''
  const viewerStyle = `width: ${width}; height: auto; max-width: none; display: block;`
  if (/\sstyle="/i.test(svg)) {
    return svg.replace(/\sstyle="([^"]*)"/i, ` style="$1 ${viewerStyle}"`)
  }
  return svg.replace(/<svg\b/i, `<svg style="${viewerStyle}"`)
}

export function escapeSummaryHtml(value: string): string {
  return value
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
}

function renderMermaidPlaceholder(
  index: number,
  labels: SummaryMermaidLabels,
): string {
  return [
    `<div class="summary-mermaid" data-summary-mermaid-index="${index}" data-summary-mermaid-state="loading">`,
    '<div class="summary-mermaid__toolbar">',
    '<span class="summary-mermaid__label">Mermaid</span>',
    '<div class="summary-mermaid__actions">',
    `<button type="button" class="summary-mermaid__copy" data-summary-mermaid-action="copy" data-summary-mermaid-index="${index}">${escapeSummaryHtml(labels.copySource)}</button>`,
    `<button type="button" class="summary-mermaid__expand" data-summary-mermaid-action="zoom" data-summary-mermaid-index="${index}">${escapeSummaryHtml(labels.openLarge)}</button>`,
    '</div>',
    '</div>',
    `<div class="summary-mermaid__canvas" data-summary-mermaid-canvas="${index}">${escapeSummaryHtml(labels.loading)}</div>`,
    '</div>',
  ].join('')
}

export function renderSummaryMarkdownWithMermaid(
  text: string,
  renderMarkdown: (value: string) => string,
  labels: SummaryMermaidLabels,
): { html: string, diagrams: SummaryMermaidDiagram[] } {
  const diagrams: SummaryMermaidDiagram[] = []
  const mermaidFencePattern =
    /(^|\n)(`{3,}|~{3,})[ \t]*mermaid[^\n]*\n([\s\S]*?)\n\2[ \t]*(?=\n|$)/gi
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
    html += renderMermaidPlaceholder(index, labels)
    lastIndex = mermaidFencePattern.lastIndex
  }

  const after = text.slice(lastIndex)
  if (after) html += renderMarkdown(after)
  return {
    html: html || renderMarkdown(text),
    diagrams,
  }
}

export function renderSummaryMermaidError(
  source: string,
  error: unknown,
  errorLabel: string,
): string {
  const message = error instanceof Error ? error.message : String(error)
  return [
    `<div class="summary-mermaid__error">${escapeSummaryHtml(errorLabel)}</div>`,
    `<pre class="md-code-block hljs"><code>${escapeSummaryHtml(source)}</code></pre>`,
    message
      ? `<div class="summary-mermaid__error-detail">${escapeSummaryHtml(message)}</div>`
      : '',
  ].join('')
}
