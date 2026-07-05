import {
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type CSSProperties,
  type Ref,
} from 'vue'

interface SummaryCollapseFloatOptions {
  summaryExpanded: Ref<boolean>
  mermaidViewerVisible: Ref<boolean>
  summaryViewerVisible: Ref<boolean>
  summaryRenderedHtml: Ref<string>
}

const HIDDEN_STYLE: CSSProperties = {
  display: 'none',
  left: '0px',
  top: '0px',
  visibility: 'hidden',
}

export function useSummaryCollapseFloat(options: SummaryCollapseFloatOptions) {
  const summaryCardRef = ref<HTMLElement | null>(null)
  const summaryCollapseFloatStyle = ref<CSSProperties>(HIDDEN_STYLE)
  let updateFrame = 0

  function update() {
    updateFrame = 0
    const card = summaryCardRef.value
    if (
      !options.summaryExpanded.value
      || options.mermaidViewerVisible.value
      || options.summaryViewerVisible.value
      || !card
    ) {
      summaryCollapseFloatStyle.value = HIDDEN_STYLE
      return
    }

    const rect = card.getBoundingClientRect()
    const visibleTop = Math.max(rect.top, 0)
    const visibleBottom = Math.min(rect.bottom, window.innerHeight)
    const nearSummaryEnd = rect.bottom <= window.innerHeight + 160
    if (visibleBottom <= visibleTop || nearSummaryEnd) {
      summaryCollapseFloatStyle.value = HIDDEN_STYLE
      return
    }

    summaryCollapseFloatStyle.value = {
      display: 'flex',
      left: `${rect.left + rect.width / 2}px`,
      top: `${Math.max(visibleTop + 44, visibleBottom - 12)}px`,
      visibility: 'visible',
    }
  }

  function scheduleUpdate() {
    if (updateFrame) return
    updateFrame = window.requestAnimationFrame(update)
  }

  onMounted(() => {
    window.addEventListener('scroll', scheduleUpdate, true)
    window.addEventListener('resize', scheduleUpdate)
  })

  onBeforeUnmount(() => {
    window.removeEventListener('scroll', scheduleUpdate, true)
    window.removeEventListener('resize', scheduleUpdate)
    if (updateFrame) window.cancelAnimationFrame(updateFrame)
  })

  watch(
    [
      options.summaryExpanded,
      options.mermaidViewerVisible,
      options.summaryViewerVisible,
      options.summaryRenderedHtml,
    ],
    async () => {
      await nextTick()
      scheduleUpdate()
    },
  )

  return {
    summaryCardRef,
    summaryCollapseFloatStyle,
  }
}
