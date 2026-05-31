import { describe, expect, it } from 'vitest'
import taskResultPanelSource from './TaskResultPanel.vue?raw'

function cssBlock(selector: string): string {
  const start = taskResultPanelSource.indexOf(`${selector} {`)
  expect(start).toBeGreaterThanOrEqual(0)
  const end = taskResultPanelSource.indexOf('}', start)
  expect(end).toBeGreaterThan(start)
  return taskResultPanelSource.slice(start, end + 1)
}

describe('TaskResultPanel', () => {
  it('uses a lighter tabular UI font for change line numbers', () => {
    const commitStats = cssBlock('.commit-stats')

    expect(commitStats).toContain('font-family: var(--n-font-family-mono, monospace);')
    expect(commitStats).toContain('font-variant-numeric: tabular-nums;')
  })

  it('execution summary card is guarded by v-if="lastAssistantLog" and uses result-card--summary-text class', () => {
    expect(taskResultPanelSource).toContain('v-if="lastAssistantLog"')
    expect(taskResultPanelSource).toContain('result-card--summary-text')
    // Both must appear together on the same element
    const summaryCardIndex = taskResultPanelSource.indexOf('result-card--summary-text')
    const nearbySource = taskResultPanelSource.slice(Math.max(0, summaryCardIndex - 60), summaryCardIndex + 60)
    expect(nearbySource).toContain('lastAssistantLog')
  })

  it('summary panel starts collapsed (summaryExpanded initialised to ref(false))', () => {
    expect(taskResultPanelSource).toContain('const summaryExpanded = ref(false)')
  })

  it('context compact count item is guarded by v-if="contextCompactCount != null"', () => {
    expect(taskResultPanelSource).toContain('v-if="contextCompactCount != null"')
  })
})
