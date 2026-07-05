import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Stats } from '../../api'
import { useMonitorData } from './useMonitorData'

const { apiMocks, messageMocks } = vi.hoisted(() => ({
  apiMocks: {
    getContainers: vi.fn(),
    getStats: vi.fn(),
    getTasks: vi.fn(),
    getTasksPaginated: vi.fn(),
  },
  messageMocks: {
    error: vi.fn(),
  },
}))

vi.mock('../../api', () => apiMocks)
vi.mock('naive-ui', () => ({
  useMessage: () => messageMocks,
}))
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))

const EMPTY_STATS: Stats = {
  total: 0,
  pending: 0,
  queued: 0,
  running: 0,
  completed: 0,
  failed: 0,
  cancelled: 0,
  completed_24h: 0,
  failed_cancelled_24h: 0,
  running_long_30min: 0,
}

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((resolvePromise) => {
    resolve = resolvePromise
  })
  return { promise, resolve }
}

describe('useMonitorData', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.clearAllMocks()
    apiMocks.getContainers.mockResolvedValue([])
    apiMocks.getTasks.mockResolvedValue([])
    apiMocks.getTasksPaginated.mockResolvedValue({ items: [] })
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it('does not start timers or replay a pending refresh after unmount', async () => {
    const statsResult = deferred<Stats>()
    apiMocks.getStats.mockReturnValueOnce(statsResult.promise)
    let monitorData!: ReturnType<typeof useMonitorData>
    const wrapper = mount(
      defineComponent({
        setup() {
          monitorData = useMonitorData()
          return () => null
        },
      }),
    )
    await Promise.resolve()
    await monitorData.fetchData({ silent: true })

    wrapper.unmount()
    statsResult.resolve(EMPTY_STATS)
    await flushPromises()
    vi.advanceTimersByTime(16_000)

    expect(apiMocks.getStats).toHaveBeenCalledOnce()
    expect(vi.getTimerCount()).toBe(0)
    expect(messageMocks.error).not.toHaveBeenCalled()
  })
})
