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

    expect(commitStats).toContain('font-family: var(--n-font-family, inherit);')
    expect(commitStats).toContain('font-size: 25px;')
    expect(commitStats).toContain('font-weight: 400;')
    expect(commitStats).toContain('font-variant-numeric: tabular-nums;')
    expect(commitStats).toContain("font-feature-settings: 'tnum';")
  })
})
