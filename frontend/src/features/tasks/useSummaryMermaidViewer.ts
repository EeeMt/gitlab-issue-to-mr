import {
  computed,
  nextTick,
  onBeforeUnmount,
  ref,
  watch,
  type CSSProperties,
  type Ref,
} from 'vue'
import { useI18n } from 'vue-i18n'

import {
  applyMermaidViewerSvgStyle,
  type SummaryMermaidDiagram,
} from './summaryMermaid'

export type MermaidZoom = 'fit' | '100' | '150' | '200' | '300' | 'custom'

export function useSummaryMermaidViewer(
  diagrams: Ref<SummaryMermaidDiagram[]>,
) {
  const { t } = useI18n()
  const mermaidViewerVisible = ref(false)
  const activeMermaidIndex = ref<number | null>(null)
  const mermaidZoomMin = 10
  const mermaidZoomMax = 2000
  const mermaidZoom = ref<MermaidZoom>('fit')
  const mermaidCustomZoom = ref(100)
  const mermaidViewerDragging = ref(false)
  let mermaidViewerDrag: {
    container: HTMLElement
    startX: number
    startY: number
    scrollLeft: number
    scrollTop: number
  } | null = null

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
    return diagrams.value[activeMermaidIndex.value]?.svg ?? ''
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
    applyMermaidViewerSvgStyle(activeMermaidRawSvg.value, '100%')
  )

  const mermaidViewerScrollbarKey = computed(() =>
    `${activeMermaidIndex.value ?? 'none'}-${mermaidZoom.value}-${mermaidCustomZoom.value}-${activeMermaidRawSvg.value.length}`
  )

  function clampMermaidZoom(value: number) {
    return Math.min(mermaidZoomMax, Math.max(mermaidZoomMin, Math.round(value)))
  }

  function handleMermaidCustomZoom(value: number | null) {
    if (value == null) return
    mermaidCustomZoom.value = clampMermaidZoom(value)
    mermaidZoom.value = 'custom'
  }

  function selectMermaidZoom(value: MermaidZoom) {
    mermaidZoom.value = value
    if (value === 'fit') {
      mermaidCustomZoom.value = 100
    } else if (value !== 'custom') {
      mermaidCustomZoom.value = Number(value)
    }
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
    const canDrag = container.scrollWidth > container.clientWidth
      || container.scrollHeight > container.clientHeight
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
    const nextContainer = modal.querySelector<HTMLElement>(
      '.summary-mermaid-modal__viewport .n-scrollbar-container',
    )
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

  watch(mermaidViewerVisible, (visible) => {
    if (!visible) stopMermaidViewerDrag()
  })

  onBeforeUnmount(stopMermaidViewerDrag)

  return {
    activeMermaidIndex,
    activeMermaidViewerSvg,
    handleMermaidCustomZoom,
    handleMermaidViewerMouseDown,
    handleMermaidViewerWheel,
    mermaidCustomZoom,
    mermaidViewerCanvasStyle,
    mermaidViewerContentStyle,
    mermaidViewerDragging,
    mermaidViewerScrollbarKey,
    mermaidViewerVisible,
    mermaidZoom,
    mermaidZoomMax,
    mermaidZoomMin,
    mermaidZoomOptions,
    resetMermaidViewer,
    selectMermaidZoom,
  }
}
