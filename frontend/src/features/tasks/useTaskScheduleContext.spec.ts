import { beforeEach, describe, expect, it, vi } from 'vitest'

const { mockGetConfig, mockGetScheduledTasks } = vi.hoisted(() => ({
  mockGetConfig: vi.fn(),
  mockGetScheduledTasks: vi.fn(),
}))

vi.mock('../../api', () => ({
  getConfig: mockGetConfig,
  getScheduledTasks: mockGetScheduledTasks,
}))

import { useTaskScheduleContext } from './useTaskScheduleContext'

describe('useTaskScheduleContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockGetScheduledTasks.mockResolvedValue([{ id: 1 }])
    mockGetConfig.mockResolvedValue({
      runtime: {
        slot_max_tasks: 5,
        slot_max_tasks_enforce: true,
      }
    })
  })

  it('loads scheduled tasks and capacity configuration', async () => {
    const context = useTaskScheduleContext()

    await context.loadScheduleContext()

    expect(context.scheduledTasks.value).toEqual([{ id: 1 }])
    expect(context.slotMaxTasks.value).toBe(5)
    expect(context.slotEnforce.value).toBe(true)
  })

  it('reuses cached tasks unless a refresh is requested', async () => {
    const context = useTaskScheduleContext()
    await context.loadScheduleContext()
    await context.loadScheduleContext()
    await context.loadScheduleContext(true)

    expect(mockGetScheduledTasks).toHaveBeenCalledTimes(2)
    expect(mockGetConfig).toHaveBeenCalledTimes(3)
  })

  it('keeps safe defaults when APIs fail', async () => {
    mockGetScheduledTasks.mockRejectedValue(new Error('tasks failed'))
    mockGetConfig.mockRejectedValue(new Error('config failed'))
    const context = useTaskScheduleContext()

    await context.loadScheduleContext()

    expect(context.scheduledTasks.value).toEqual([])
    expect(context.slotConfigLoadFailed.value).toBe(true)
  })
})
