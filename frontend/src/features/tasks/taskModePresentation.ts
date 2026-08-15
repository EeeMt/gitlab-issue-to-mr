import type { TaskMode } from '../../api/tasks'

export type PresentedTaskMode = TaskMode | 'unknown'
export type TaskModeIcon = 'implementation' | 'freeform' | 'analysis' | 'unknown'

export interface TaskModePresentation {
  mode: PresentedTaskMode
  i18nKey:
    | 'taskView.taskModeExecute'
    | 'taskView.taskModeFreeform'
    | 'taskView.taskModePlan'
    | 'taskView.taskModeUnknown'
  modifier: PresentedTaskMode
  icon: TaskModeIcon
}

const TASK_MODE_PRESENTATIONS: Record<PresentedTaskMode, TaskModePresentation> = {
  execute: {
    mode: 'execute',
    i18nKey: 'taskView.taskModeExecute',
    modifier: 'execute',
    icon: 'implementation',
  },
  freeform: {
    mode: 'freeform',
    i18nKey: 'taskView.taskModeFreeform',
    modifier: 'freeform',
    icon: 'freeform',
  },
  plan: {
    mode: 'plan',
    i18nKey: 'taskView.taskModePlan',
    modifier: 'plan',
    icon: 'analysis',
  },
  unknown: {
    mode: 'unknown',
    i18nKey: 'taskView.taskModeUnknown',
    modifier: 'unknown',
    icon: 'unknown',
  },
}

export const TASK_MODE_BREAKDOWN_ORDER = [
  'freeform',
  'execute',
  'plan',
  'unknown',
] as const satisfies readonly PresentedTaskMode[]

export function getTaskModePresentation(value: unknown): TaskModePresentation {
  if (value === 'execute' || value === 'freeform' || value === 'plan') {
    return TASK_MODE_PRESENTATIONS[value]
  }
  return TASK_MODE_PRESENTATIONS.unknown
}
