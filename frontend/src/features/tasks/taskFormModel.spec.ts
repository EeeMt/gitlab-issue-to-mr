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
  sessionMode: 'continue',
  harnessKey: null,
  selectedProviderId: null,
  scheduleType: 'now',
  scheduledAt: null,
  runInstructionTemplate: 'Execute {{user_prompt}}',
  runInstructionDirty: false,
  inheritProfileSkills: true,
  selectedSkillIds: [],
  skillSelectionDirty: false,
}

const existingTask = {
  id: 12,
  user_prompt: 'Implement it',
  priority: 1,
  require_changes: true,
  task_mode: 'execute',
  provider_id: 3,
  worker_profile_id: 4,
  skill_ids: [2],
  skill_names: ['review'],
  skill_selection_source: 'profile',
} as Task

describe('task form request contracts', () => {
  it('builds the default execute request without requiring changes', () => {
    expect(buildCreateTaskRequest(7, baseDraft)).toEqual({
      issue_id: 7,
      priority: 1,
      task_mode: 'execute',
      require_changes: false,
      session_mode: 'continue',
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

  it('builds a canonical-free freeform create request', () => {
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      taskMode: 'freeform',
      requireChanges: true,
      runInstructionTemplate: '{{user_prompt}}',
      runInstructionDirty: true,
    })).toEqual({
      issue_id: 7,
      priority: 1,
      task_mode: 'freeform',
      require_changes: false,
      session_mode: 'continue',
      user_prompt: 'Implement it',
    })
  })

  it('includes only explicitly selected create options', () => {
    const scheduledAt = Date.UTC(2026, 6, 5, 10)
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      selectedProviderId: 3,
      scheduleType: 'scheduled',
      scheduledAt,
      runInstructionDirty: true,
    })).toEqual({
      issue_id: 7,
      priority: 1,
      task_mode: 'execute',
      require_changes: false,
      session_mode: 'continue',
      user_prompt: 'Implement it',
      provider_id: 3,
      scheduled_datetime: new Date(scheduledAt).toISOString(),
      run_instruction_template: 'Execute {{user_prompt}}',
    })
  })

  it('keeps an explicitly edited plan template while forcing require_changes false', () => {
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      taskMode: 'plan',
      requireChanges: true,
      runInstructionTemplate: 'Custom plan {{user_prompt}}',
      runInstructionDirty: true,
    })).toEqual(expect.objectContaining({
      task_mode: 'plan',
      require_changes: false,
      run_instruction_template: 'Custom plan {{user_prompt}}',
    }))
  })

  it('includes harness_key when a non-default harness is selected', () => {
    expect(buildCreateTaskRequest(7, { ...baseDraft, harnessKey: 'codex' })).toEqual(
      expect.objectContaining({
        issue_id: 7,
        harness_key: 'codex',
      }),
    )
  })

  it('requests a fresh Claude session when selected', () => {
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      sessionMode: 'fresh',
    }).session_mode).toBe('fresh')
  })

  it('sends a complete task-level skill override including an explicit empty selection', () => {
    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      inheritProfileSkills: false,
      selectedSkillIds: [],
    }).skill_ids).toEqual([])

    expect(buildCreateTaskRequest(7, {
      ...baseDraft,
      inheritProfileSkills: false,
      selectedSkillIds: [3, 5],
    }).skill_ids).toEqual([3, 5])
  })

  it('restores profile skill inheritance with an explicit null update', () => {
    expect(buildUpdateTaskRequest({
      ...existingTask,
      skill_selection_source: 'task',
    }, {
      ...baseDraft,
      requireChanges: true,
      selectedProviderId: 3,
      inheritProfileSkills: true,
    }, baseDraft.runInstructionTemplate)).toEqual({ skill_ids: null })
  })

  it('refreshes or clears a frozen task Skill snapshot after explicit user action', () => {
    expect(buildUpdateTaskRequest({
      ...existingTask,
      skill_selection_source: 'task',
      skill_ids: [2],
    }, {
      ...baseDraft,
      requireChanges: true,
      selectedProviderId: 3,
      inheritProfileSkills: false,
      selectedSkillIds: [2],
      skillSelectionDirty: true,
    }, baseDraft.runInstructionTemplate)).toEqual({ skill_ids: [2] })

    expect(buildUpdateTaskRequest({
      ...existingTask,
      skill_selection_source: 'task',
      skill_ids: [],
    }, {
      ...baseDraft,
      requireChanges: true,
      selectedProviderId: 3,
      inheritProfileSkills: false,
      selectedSkillIds: [],
      skillSelectionDirty: true,
    }, baseDraft.runInstructionTemplate)).toEqual({ skill_ids: [] })
  })

  it('builds a minimal edit patch', () => {
    expect(buildUpdateTaskRequest(existingTask, {
      ...baseDraft,
      requireChanges: true,
      selectedProviderId: 3,
    }, baseDraft.runInstructionTemplate)).toEqual({})
  })

  it('enforces the plan invariant in an edit patch', () => {
    expect(buildUpdateTaskRequest(existingTask, {
      ...baseDraft,
      taskMode: 'plan',
      requireChanges: true,
      selectedProviderId: 3,
    }, baseDraft.runInstructionTemplate)).toEqual({
      task_mode: 'plan',
      require_changes: false,
    })
  })

  it('lets the backend normalize a switch to freeform from only the mode patch', () => {
    expect(buildUpdateTaskRequest(existingTask, {
      ...baseDraft,
      taskMode: 'freeform',
      requireChanges: true,
      selectedProviderId: 3,
    }, baseDraft.runInstructionTemplate)).toEqual({
      task_mode: 'freeform',
    })
  })

  it.each(['execute', 'plan'] as const)(
    'does not carry the freeform canonical template when switching back to %s',
    (taskMode) => {
      const freeformTask = {
        ...existingTask,
        require_changes: false,
        task_mode: 'freeform',
        run_instruction_template: '{{user_prompt}}',
      } as Task

      expect(buildUpdateTaskRequest(freeformTask, {
        ...baseDraft,
        taskMode,
        requireChanges: false,
        selectedProviderId: 3,
        runInstructionTemplate: taskMode === 'execute'
          ? 'Execute {{user_prompt}}'
          : 'Plan {{user_prompt}}',
        runInstructionDirty: false,
      }, '{{user_prompt}}')).toEqual({
        task_mode: taskMode,
      })
    },
  )

  it.each(['execute', 'plan'] as const)(
    'keeps sending an explicitly edited %s template',
    (taskMode) => {
      expect(buildUpdateTaskRequest(existingTask, {
        ...baseDraft,
        taskMode,
        requireChanges: taskMode === 'execute',
        selectedProviderId: 3,
        runInstructionTemplate: `Custom ${taskMode}`,
        runInstructionDirty: true,
      }, baseDraft.runInstructionTemplate)).toEqual({
        ...(taskMode === 'plan' ? { task_mode: 'plan', require_changes: false } : {}),
        run_instruction_template: `Custom ${taskMode}`,
      })
    },
  )
})
