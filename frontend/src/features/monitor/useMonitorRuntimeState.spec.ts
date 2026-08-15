import { ref } from 'vue'
import { describe, expect, it } from 'vitest'
import type { Container, Stats, Task } from '../../api'
import { createMockTask } from '../../test/mocks/api'
import { useMonitorRuntimeState } from './useMonitorRuntimeState'

const translate = (key: string) => key

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

// Fixed "now" so scheduled_at comparisons are deterministic.
const NOW_MS = new Date('2026-03-31T12:00:00Z').getTime()
const BEFORE_NOW = '2026-03-31T08:00:00Z'
const AFTER_NOW = '2026-03-31T16:00:00Z'

function createState(tasks: Task[]) {
  return useMonitorRuntimeState({
    stats: ref(EMPTY_STATS),
    containers: ref<Container[]>([]),
    tasks: ref(tasks),
    recentFinishedList: ref<Task[]>([]),
    recentFailureList: ref<Task[]>([]),
    nowMs: ref(NOW_MS),
    translate,
  })
}

describe('useMonitorRuntimeState sequence-repair partition', () => {
  it('excludes sequence_repair_required tasks from readyTasks', () => {
    const repair = createMockTask({
      id: 1,
      status: 'pending',
      waiting_reason: 'sequence_repair_required',
      queue_position: null,
      scheduled_at: null,
    })
    const ready = createMockTask({
      id: 2,
      status: 'pending',
      waiting_reason: null,
      queue_position: 1,
      scheduled_at: null,
    })
    const state = createState([repair, ready])

    expect(state.readyTasks.value.map((t) => t.id)).toEqual([2])
    expect(state.sequenceRepairTasks.value.map((t) => t.id)).toEqual([1])
  })

  it('excludes sequence_repair_required tasks from waitingTasks', () => {
    const repair = createMockTask({
      id: 1,
      status: 'queued',
      waiting_reason: 'sequence_repair_required',
      queue_position: 1,
      scheduled_at: AFTER_NOW,
    })
    const waiting = createMockTask({
      id: 2,
      status: 'queued',
      waiting_reason: null,
      queue_position: 1,
      scheduled_at: AFTER_NOW,
    })
    const state = createState([repair, waiting])

    expect(state.waitingTasks.value.map((t) => t.id)).toEqual([2])
    expect(state.sequenceRepairTasks.value.map((t) => t.id)).toEqual([1])
  })

  it('excludes sequence_repair_required tasks from waitingForPredecessors', () => {
    const repair = createMockTask({
      id: 1,
      status: 'pending',
      waiting_reason: 'sequence_repair_required',
      queue_position: 3,
      scheduled_at: null,
    })
    const blocked = createMockTask({
      id: 2,
      status: 'queued',
      waiting_reason: 'predecessor',
      queue_position: 3,
      scheduled_at: null,
    })
    const state = createState([repair, blocked])

    expect(state.waitingForPredecessors.value.map((t) => t.id)).toEqual([2])
    expect(state.sequenceRepairTasks.value.map((t) => t.id)).toEqual([1])
  })

  it('partitions pending/queued tasks into disjoint buckets', () => {
    const repairReady = createMockTask({
      id: 1,
      status: 'pending',
      waiting_reason: 'sequence_repair_required',
      queue_position: null,
      scheduled_at: null,
    })
    const ready = createMockTask({
      id: 2,
      status: 'pending',
      waiting_reason: null,
      queue_position: null,
      scheduled_at: BEFORE_NOW,
    })
    const waiting = createMockTask({
      id: 3,
      status: 'queued',
      waiting_reason: null,
      queue_position: 1,
      scheduled_at: AFTER_NOW,
    })
    const blocked = createMockTask({
      id: 4,
      status: 'queued',
      waiting_reason: 'workspace_cleanup',
      queue_position: 2,
      scheduled_at: null,
    })
    const state = createState([repairReady, ready, waiting, blocked])

    expect(state.readyTasks.value.map((t) => t.id)).toEqual([2])
    expect(state.waitingTasks.value.map((t) => t.id)).toEqual([3])
    expect(state.waitingForPredecessors.value.map((t) => t.id)).toEqual([4])
    expect(state.sequenceRepairTasks.value.map((t) => t.id)).toEqual([1])

    const all = [
      ...state.readyTasks.value,
      ...state.waitingTasks.value,
      ...state.waitingForPredecessors.value,
      ...state.sequenceRepairTasks.value,
    ]
    const ids = all.map((t) => t.id)
    expect(new Set(ids).size).toBe(ids.length)
    expect(ids.sort()).toEqual([1, 2, 3, 4])
  })
})
