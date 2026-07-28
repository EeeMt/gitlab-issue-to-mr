import type {
  CreateTaskRequest,
  Task,
  UpdateTaskRequest,
} from '../../api/tasks'

export type TaskMode = 'execute' | 'plan'
export type TaskScheduleType = 'now' | 'scheduled'

export const DEFAULT_TASK_PRIORITY = 1
export const DEFAULT_REQUIRE_CHANGES = false

export interface TaskFormDraft {
  prompt: string
  priority: number
  requireChanges: boolean
  taskMode: TaskMode
  sessionMode: 'continue' | 'fresh'
  selectedProviderId: number | null
  scheduleType: TaskScheduleType
  scheduledAt: number | null
  runInstructionTemplate: string
  runInstructionDirty: boolean
  inheritProfileSkills: boolean
  selectedSkillIds: number[]
  skillSelectionDirty: boolean
}

export function buildCreateTaskRequest(
  issueId: number,
  draft: TaskFormDraft,
): CreateTaskRequest {
  const request: CreateTaskRequest = {
    issue_id: issueId,
    priority: draft.priority,
    task_mode: draft.taskMode,
    require_changes: draft.taskMode === 'plan' ? false : draft.requireChanges,
    session_mode: draft.sessionMode,
  }
  const prompt = draft.prompt.trim()
  if (prompt) request.user_prompt = prompt
  if (draft.runInstructionDirty) {
    request.run_instruction_template = draft.runInstructionTemplate
  }
  if (draft.scheduleType === 'scheduled' && draft.scheduledAt !== null) {
    request.scheduled_datetime = new Date(draft.scheduledAt).toISOString()
  }
  if (draft.selectedProviderId !== null) {
    request.provider_id = draft.selectedProviderId
  }
  if (!draft.inheritProfileSkills) {
    request.skill_ids = [...draft.selectedSkillIds]
  }
  return request
}

export function buildUpdateTaskRequest(
  original: Task,
  draft: Omit<TaskFormDraft, 'scheduleType' | 'scheduledAt'>,
  initialRunInstructionTemplate: string,
): UpdateTaskRequest {
  const request: UpdateTaskRequest = {}
  const prompt = draft.prompt.trim()

  if (prompt !== original.user_prompt) request.user_prompt = prompt
  if (draft.priority !== original.priority) request.priority = draft.priority
  if (draft.selectedProviderId !== (original.provider_id ?? null)) {
    request.provider_id = draft.selectedProviderId
  }
  if (draft.requireChanges !== original.require_changes) {
    request.require_changes = draft.requireChanges
  }
  if (draft.taskMode !== (original.task_mode ?? 'execute')) {
    request.task_mode = draft.taskMode
  }
  if (draft.taskMode === 'plan' && original.require_changes !== false) {
    request.require_changes = false
  }
  if (draft.runInstructionTemplate !== initialRunInstructionTemplate) {
    request.run_instruction_template = draft.runInstructionTemplate
  }
  if (draft.inheritProfileSkills) {
    if (
      draft.skillSelectionDirty
      || (original.skill_selection_source ?? 'profile') !== 'profile'
    ) {
      request.skill_ids = null
    }
  } else {
    const originalSkillIds = original.skill_ids ?? []
    if (
      draft.skillSelectionDirty
      ||
      (original.skill_selection_source ?? 'profile') !== 'task'
      || JSON.stringify(draft.selectedSkillIds) !== JSON.stringify(originalSkillIds)
    ) {
      request.skill_ids = [...draft.selectedSkillIds]
    }
  }

  return request
}
