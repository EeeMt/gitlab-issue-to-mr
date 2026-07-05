import { onBeforeUnmount, ref, type Ref } from 'vue'
import { useMessage } from 'naive-ui'
import { useI18n } from 'vue-i18n'

import type { SummaryMermaidDiagram } from './summaryMermaid'
import type { MermaidZoom } from './useSummaryMermaidViewer'

interface SummaryCopyActionsOptions {
  summaryText: Readonly<Ref<string>>
  diagrams: Readonly<Ref<SummaryMermaidDiagram[]>>
  loadSummaryPayloadIfNeeded: () => Promise<boolean>
  activeMermaidIndex: Ref<number | null>
  mermaidViewerVisible: Ref<boolean>
  selectMermaidZoom: (zoom: MermaidZoom) => void
}

export function useSummaryCopyActions(options: SummaryCopyActionsOptions) {
  const { t } = useI18n()
  const message = useMessage()
  const summaryCopied = ref(false)
  let summaryCopiedTimer: ReturnType<typeof setTimeout> | undefined
  const mermaidCopyTimers = new Map<HTMLButtonElement, ReturnType<typeof setTimeout>>()

  async function copySource(source: string): Promise<boolean> {
    if (!source) {
      message.error(t('taskView.copyFailed'))
      return false
    }
    try {
      await navigator.clipboard.writeText(source)
      message.success(t('taskView.copied'))
      return true
    } catch {
      message.error(t('taskView.copyFailed'))
      return false
    }
  }

  async function copySummarySource() {
    const payloadAvailable = await options.loadSummaryPayloadIfNeeded()
    if (!payloadAvailable) return
    const copied = await copySource(options.summaryText.value)
    if (!copied) return

    summaryCopied.value = true
    if (summaryCopiedTimer) clearTimeout(summaryCopiedTimer)
    summaryCopiedTimer = setTimeout(() => {
      summaryCopied.value = false
    }, 2000)
  }

  function handleSummaryContentClick(event: MouseEvent) {
    const target = event.target
    if (!(target instanceof HTMLElement)) return

    const button = target.closest<HTMLButtonElement>('[data-summary-mermaid-action]')
    if (!button) return

    const index = Number(button.dataset.summaryMermaidIndex)
    if (!Number.isInteger(index)) return
    const diagram = options.diagrams.value[index]
    if (!diagram) return

    if (button.dataset.summaryMermaidAction === 'copy') {
      void copySource(diagram.source).then(copied => {
        if (!copied) return
        const activeTimer = mermaidCopyTimers.get(button)
        if (activeTimer) clearTimeout(activeTimer)
        button.textContent = t('taskView.copied')
        const timer = setTimeout(() => {
          button.textContent = t('taskView.copySource')
          mermaidCopyTimers.delete(button)
        }, 2000)
        mermaidCopyTimers.set(button, timer)
      })
      return
    }
    if (button.dataset.summaryMermaidAction !== 'zoom' || !diagram.svg) return

    options.activeMermaidIndex.value = index
    options.selectMermaidZoom('fit')
    options.mermaidViewerVisible.value = true
  }

  onBeforeUnmount(() => {
    if (summaryCopiedTimer) clearTimeout(summaryCopiedTimer)
    mermaidCopyTimers.forEach(timer => clearTimeout(timer))
    mermaidCopyTimers.clear()
  })

  return {
    copySummarySource,
    handleSummaryContentClick,
    summaryCopied,
  }
}
