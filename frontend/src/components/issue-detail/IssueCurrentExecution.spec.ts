import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

describe('IssueCurrentExecution styles', () => {
  it('keeps the activity line animated when motion preference media queries are unsupported', () => {
    const source = readFileSync(
      resolve(process.cwd(), 'src/components/issue-detail/IssueCurrentExecution.vue'),
      'utf8',
    )

    const activityRule = source.match(/\.execution-card__activity\s*\{[\s\S]*?\n\}/)?.[0] ?? ''

    expect(activityRule).toContain('animation: execution-activity 2.6s ease-in-out infinite')
    expect(source).toContain('@media (prefers-reduced-motion: reduce)')
  })
})
