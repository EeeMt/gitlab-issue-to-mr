import { computed } from 'vue'
import { useWindowSize } from '@vueuse/core'

const MOBILE_BREAKPOINT = 768
const COMPACT_BREAKPOINT = 480

export function useBreakpoints() {
  const { width } = useWindowSize()

  const isMobile = computed(() => width.value < MOBILE_BREAKPOINT)
  const isCompact = computed(() => width.value < COMPACT_BREAKPOINT)

  return {
    width,
    isMobile,
    isCompact,
    mobileBreakpoint: MOBILE_BREAKPOINT,
    compactBreakpoint: COMPACT_BREAKPOINT
  }
}
