import { describe, expect, it } from 'vitest'

import type { Task } from '../../api/tasks'
import {
  DEFAULT_REQUIRE_CHANGES,
  buildCreateTaskRequest,
  buildUpdateTaskRequest,
  type TaskFormDraft,
} from './taskFormModel'

const baseDraft: TaskFormDraft = {
  prompt: '  Implement it  ',
  priority: 1,
  requireChanges: DEFAULT_REQUIRE_CHANGES,
  taskMode: 'execute',
  selectedProviderId: null,
  selectedWorkerProfileId: null,
  scheduleType: 'now',
  scheduledAt: null,
  runInstructionTemplate: 'Execute {{user_prompt}}',
  runInstructionDirty: false,
}

const existingTask = {
  id: 12,
  user_prompt: 'Implement it',
  priority: 1,
  require_changes: true,
  task_mode: 'execute',
  provider_id: 3,
  worker_profile_id: 4,
} as Task

describe('task form request contracts', () => {
  it('builds the default execute request without requiring changes', () => {
    expect(buildCreateTaskRequest(7, baseDraft)).toEqual({
      issue_id: 7,
      priority: 1,
      task_mode: 'execute',
      require_changes: false,
      user_prompt: 'Implement it',
    })
  })

  it('forces plan tasks to not require changes', () => {
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      taskMode: 'plan',
      requireChanges: true,
    }).require_changes).toBe(false)
  })

  it('includes only explicitly selected create options', () => {
    const scheduledAt = Date.UTC(2026, 6, 5, 10)
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      selectedProviderId: 3,
      selectedWorkerProfileId: 4,
      scheduleType: 'scheduled',
      scheduledAt,
      runInstructionDirty: true,
    })).toEqual({
      issue_id: 7,
      priority: 1,
      task_mode: 'execute',
      require_changes: false,
      user_prompt: 'Implement it',
      provider_id: 3,
      worker_profile_id: 4,
      scheduled_datetime: new Date(scheduledAt).toISOString(),
      run_instruction_template: 'Execute {{user_prompt}}',
    })
  })

  it('builds a minimal edit patch', () => {
    expect(buildUpdateTaskRequest(existingTask, {
      ...baseDraft,
      requireChanges: true,
      selectedProviderId: 3,
      selectedWorkerProfileId: 4,
    }, baseDraft.runInstructionTemplate)).toEqual({})
  })

  it('enforces the plan invariant in an edit patch', () => {
    expect(buildUpdateTaskRequest(existingTask, {
      ...baseDraft,
      taskMode: 'plan',
      requireChanges: true,
      selectedProviderId: 3,
      selectedWorkerProfileId: 4,
    }, baseDraft.runInstructionTemplate)).toEqual({
      task_mode: 'plan',
      require_changes: false,
    })
  })
})
