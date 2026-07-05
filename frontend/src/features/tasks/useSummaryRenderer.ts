import { nextTick, ref, watch, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'

import { renderMarkdown } from '../../components/task-process/taskProcessUtils'
import {
  renderSummaryMarkdownWithMermaid,
  renderSummaryMermaidError,
  type SummaryMermaidDiagram,
} from './summaryMermaid'

interface SummaryRendererOptions {
  taskId: Readonly<Ref<number>>
  summaryText: Readonly<Ref<string>>
  diagrams: Ref<SummaryMermaidDiagram[]>
  summaryContentRef: Ref<HTMLElement | null>
  summaryViewerContentRef: Ref<HTMLElement | null>
  summaryViewerVisible: Ref<boolean>
  resetMermaidViewer: () => void
}

export function useSummaryRenderer(options: SummaryRendererOptions) {
  const { t } = useI18n()
  const summaryRenderedHtml = ref('')
  const summaryRenderedSource = ref('')
  let mermaidConfigured = false
  let mermaidRenderer: typeof import('mermaid').default | null = null
  let renderGeneration = 0

  async function getMermaidRenderer() {
    if (!mermaidRenderer) {
      mermaidRenderer = (await import('mermaid')).default
    }
    if (mermaidConfigured) return mermaidRenderer

    mermaidRenderer.initialize({
      startOnLoad: false,
      theme: 'neutral',
      securityLevel: 'strict',
      flowchart: {
        useMaxWidth: true,
        htmlLabels: true,
      },
    })
    mermaidConfigured = true
    return mermaidRenderer
  }

  function markMermaidDiagramError(
    root: HTMLElement,
    diagrams: SummaryMermaidDiagram[],
    index: number,
    error: unknown,
  ) {
    const diagram = diagrams[index]
    const container = root.querySelector<HTMLElement>(
      `[data-summary-mermaid-index="${index}"]`,
    )
    const canvas = root.querySelector<HTMLElement>(
      `[data-summary-mermaid-canvas="${index}"]`,
    )
    if (!diagram || !container || !canvas) return

    diagram.svg = ''
    diagram.error = error instanceof Error ? error.message : String(error)
    canvas.innerHTML = renderSummaryMermaidError(
      diagram.source,
      error,
      t('taskView.mermaidRenderError'),
    )
    container.dataset.summaryMermaidState = 'error'
  }

  function hydrateSummaryViewerMermaid() {
    const root = options.summaryViewerContentRef.value
    if (!root) return

    options.diagrams.value.forEach((diagram, index) => {
      const container = root.querySelector<HTMLElement>(
        `[data-summary-mermaid-index="${index}"]`,
      )
      const canvas = root.querySelector<HTMLElement>(
        `[data-summary-mermaid-canvas="${index}"]`,
      )
      if (!container || !canvas) return

      if (diagram.svg) {
        canvas.innerHTML = diagram.svg
        container.dataset.summaryMermaidState = 'ready'
      } else if (diagram.error) {
        canvas.innerHTML = renderSummaryMermaidError(
          diagram.source,
          diagram.error,
          t('taskView.mermaidRenderError'),
        )
        container.dataset.summaryMermaidState = 'error'
      }
    })
  }

  function cleanupMermaidRenderArtifacts(renderId: string) {
    document.getElementById(`d${renderId}`)?.remove()
    document.getElementById(`i${renderId}`)?.remove()
  }

  async function renderSummaryMermaidDiagrams(generation: number) {
    const diagrams = options.diagrams.value
    if (diagrams.length === 0) return

    await nextTick()
    if (generation !== renderGeneration) return
    const root = options.summaryContentRef.value
    if (!root) return

    let mermaid: typeof import('mermaid').default
    try {
      mermaid = await getMermaidRenderer()
    } catch (error) {
      if (generation !== renderGeneration) return
      diagrams.forEach((_, index) =>
        markMermaidDiagramError(root, diagrams, index, error)
      )
      options.diagrams.value = [...diagrams]
      return
    }
    if (generation !== renderGeneration) return

    await Promise.all(diagrams.map(async (diagram, index) => {
      const container = root.querySelector<HTMLElement>(
        `[data-summary-mermaid-index="${index}"]`,
      )
      const canvas = root.querySelector<HTMLElement>(
        `[data-summary-mermaid-canvas="${index}"]`,
      )
      if (!container || !canvas) return

      const renderId = `summary-mermaid-${options.taskId.value}-${generation}-${index}`
      try {
        cleanupMermaidRenderArtifacts(renderId)
        const { svg, bindFunctions } = await mermaid.render(
          renderId,
          diagram.source,
          canvas,
        )
        if (generation !== renderGeneration) return
        diagram.svg = svg
        diagram.error = ''
        canvas.innerHTML = svg
        bindFunctions?.(canvas)
        container.dataset.summaryMermaidState = 'ready'
      } catch (error) {
        if (generation !== renderGeneration) return
        markMermaidDiagramError(root, diagrams, index, error)
      } finally {
        cleanupMermaidRenderArtifacts(renderId)
      }
    }))
    options.diagrams.value = [...diagrams]
  }

  function resetSummaryRender() {
    renderGeneration += 1
    summaryRenderedHtml.value = ''
    summaryRenderedSource.value = ''
    options.diagrams.value = []
    options.resetMermaidViewer()
  }

  function syncSummaryRender() {
    const text = options.summaryText.value.trim()
    if (!text) {
      resetSummaryRender()
      return
    }
    if (summaryRenderedSource.value === text) return

    const generation = ++renderGeneration
    options.resetMermaidViewer()
    const rendered = renderSummaryMarkdownWithMermaid(text, renderMarkdown, {
      copySource: t('taskView.copySource'),
      openLarge: t('taskView.mermaidOpenLarge'),
      loading: t('taskView.mermaidLoading'),
    })
    options.diagrams.value = rendered.diagrams
    summaryRenderedHtml.value = rendered.html
    summaryRenderedSource.value = text
    if (options.diagrams.value.length > 0) {
      void renderSummaryMermaidDiagrams(generation)
    }
  }

  watch(
    [
      options.summaryViewerVisible,
      summaryRenderedHtml,
      options.diagrams,
    ],
    async () => {
      if (!options.summaryViewerVisible.value) return
      await nextTick()
      hydrateSummaryViewerMermaid()
    },
  )

  return {
    resetSummaryRender,
    summaryRenderedHtml,
    summaryRenderedSource,
    syncSummaryRender,
  }
}
