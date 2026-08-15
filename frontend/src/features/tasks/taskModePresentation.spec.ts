import { describe, expect, it } from 'vitest'

import {
  TASK_MODE_BREAKDOWN_ORDER,
  getTaskModePresentation,
} from './taskModePresentation'

describe('task mode presentation', () => {
  it.each([
    ['execute', 'taskView.taskModeExecute', 'execute', 'implementation'],
    ['freeform', 'taskView.taskModeFreeform', 'freeform', 'freeform'],
    ['plan', 'taskView.taskModePlan', 'plan', 'analysis'],
  ] as const)('maps %s to its explicit presentation', (mode, i18nKey, modifier, icon) => {
    expect(getTaskModePresentation(mode)).toEqual({
      mode,
      i18nKey,
      modifier,
      icon,
    })
  })

  it.each([null, undefined, '', 'legacy-mode'])(
    'maps historical or unknown value %s to Unknown instead of Implementation',
    (mode) => {
      expect(getTaskModePresentation(mode)).toEqual({
        mode: 'unknown',
        i18nKey: 'taskView.taskModeUnknown',
        modifier: 'unknown',
        icon: 'unknown',
      })
    },
  )

  it('exports the fixed statistics order with Unknown last', () => {
    expect(TASK_MODE_BREAKDOWN_ORDER).toEqual(['freeform', 'execute', 'plan', 'unknown'])
  })
})
