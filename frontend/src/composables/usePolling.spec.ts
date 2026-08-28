import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { usePolling, type UsePollingOptions } from './usePolling'

/**
 * Helper to run a composable inside a proper Vue component context
 * so that `onUnmounted` and other lifecycle hooks work correctly.
 */
function withSetup(composableFn: () => ReturnType<typeof usePolling>) {
  let result!: ReturnType<typeof usePolling>
  const App = defineComponent({
    setup() {
      result = composableFn()
      return () => null
    },
  })
  const wrapper = mount(App)
  return { result, wrapper }
}

describe('usePolling', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    // Default: tab is visible so the interval callback fires normally
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    })
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  // ─── immediate behaviour ────────────────────────────────────────────
  it('calls fn immediately on start() when immediate is true (default)', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()

    expect(fn).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('calls fn immediately on start() when immediate is explicitly true', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000, immediate: true }),
    )

    result.start()

    expect(fn).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does NOT call fn immediately on start() when immediate is false', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000, immediate: false }),
    )

    result.start()

    expect(fn).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  // ─── interval ticks ─────────────────────────────────────────────────
  it('calls fn again after the interval elapses', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 5000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1) // immediate call

    vi.advanceTimersByTime(5000)
    expect(fn).toHaveBeenCalledTimes(2)

    vi.advanceTimersByTime(5000)
    expect(fn).toHaveBeenCalledTimes(3)

    wrapper.unmount()
  })

  it('does not call fn before the interval elapses', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 5000, immediate: false }),
    )

    result.start()
    vi.advanceTimersByTime(4999)
    expect(fn).not.toHaveBeenCalled()

    vi.advanceTimersByTime(1)
    expect(fn).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  // ─── stop ───────────────────────────────────────────────────────────
  it('stop() prevents further fn calls', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1)

    result.stop()

    vi.advanceTimersByTime(5000)
    // no additional calls after stop
    expect(fn).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  // ─── isActive ───────────────────────────────────────────────────────
  it('isActive is false initially', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    expect(result.isActive.value).toBe(false)
    wrapper.unmount()
  })

  it('isActive becomes true after start()', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    expect(result.isActive.value).toBe(true)

    wrapper.unmount()
  })

  it('isActive becomes false after stop()', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    result.stop()
    expect(result.isActive.value).toBe(false)

    wrapper.unmount()
  })

  // ─── restart ────────────────────────────────────────────────────────
  it('start() after stop() restarts polling', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1) // immediate
    result.stop()

    fn.mockClear()

    result.start()
    expect(fn).toHaveBeenCalledTimes(1) // second immediate call
    expect(result.isActive.value).toBe(true)

    vi.advanceTimersByTime(1000)
    expect(fn).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  // ─── duplicate start protection ─────────────────────────────────────
  it('calling start() twice does not create duplicate timers', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    result.start() // second start – should clear the first timer
    expect(fn).toHaveBeenCalledTimes(2) // two immediate calls

    fn.mockClear()

    // After one interval, fn should fire exactly once (not twice)
    vi.advanceTimersByTime(1000)
    expect(fn).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })

  // ─── onUnmounted cleanup ───────────────────────────────────────────
  it('automatically stops polling when the component unmounts', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1)

    wrapper.unmount()

    vi.advanceTimersByTime(5000)
    // no additional calls after unmount
    expect(fn).toHaveBeenCalledTimes(1)
  })

  // ─── skipWhenHidden ─────────────────────────────────────────────────
  it('skips interval tick when tab is hidden and skipWhenHidden is true (default)', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1)

    // Simulate hidden tab
    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      writable: true,
      configurable: true,
    })

    vi.advanceTimersByTime(1000)
    // fn should NOT be called because tab is hidden
    expect(fn).toHaveBeenCalledTimes(1)

    // Make visible again
    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    })

    vi.advanceTimersByTime(1000)
    expect(fn).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  it('does NOT skip interval tick when skipWhenHidden is false', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 1000, skipWhenHidden: false }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1)

    // Simulate hidden tab
    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      writable: true,
      configurable: true,
    })

    vi.advanceTimersByTime(1000)
    // fn SHOULD be called even though tab is hidden
    expect(fn).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  it('refreshes immediately when a hidden tab becomes visible', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 5000 }),
    )

    result.start()
    expect(fn).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', {
      value: 'hidden',
      writable: true,
      configurable: true,
    })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(fn).toHaveBeenCalledTimes(1)

    Object.defineProperty(document, 'visibilityState', {
      value: 'visible',
      writable: true,
      configurable: true,
    })
    document.dispatchEvent(new Event('visibilitychange'))
    expect(fn).toHaveBeenCalledTimes(2)

    wrapper.unmount()
  })

  it('does not refresh on visibility changes after polling stops', () => {
    const fn = vi.fn()
    const { result, wrapper } = withSetup(() =>
      usePolling(fn, { interval: 5000 }),
    )

    result.start()
    result.stop()

    document.dispatchEvent(new Event('visibilitychange'))
    expect(fn).toHaveBeenCalledTimes(1)

    wrapper.unmount()
  })
})
