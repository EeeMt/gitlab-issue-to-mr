import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const LABEL_FILES = [
  'src/views/Monitor.vue',
  'src/components/issue-detail/IssueCurrentExecution.vue',
  'src/components/issue-detail/IssueTaskRecord.vue',
  'src/views/TaskView.vue',
]

function source(rel: string): string {
  return readFileSync(resolve(process.cwd(), rel), 'utf8')
}

describe('workspace_cleanup queue-context label', () => {
  it('renders the lock owner (lock_owner_task_id), not blocked_by_task_id', () => {
    for (const rel of LABEL_FILES) {
      const src = source(rel)
      const marker = "waiting_reason === 'workspace_cleanup'"
      expect(src, rel).toContain(marker)
      // Capture the workspace_cleanup branch: the label must be built from the
      // lock holder (lock_owner_task_id), never the legacy blocked_by_task_id
      // (which is null for workspace_cleanup; the holder lives in lock_owner).
      const branch = src.slice(src.indexOf(marker), src.indexOf(marker) + 300)
      expect(branch, rel).toContain('lock_owner_task_id')
      expect(branch, rel).not.toContain('blocked_by_task_id')
    }
  })

  it('uses the {blockedBy} interpolation param in i18n messages', () => {
    // The message param stays {blockedBy}; the call sites pass the lock owner
    // id as that value. Keep the i18n contract pinned here so a future rename
    // cannot silently break the rendered "Waiting for Task #<owner_id>".
    for (const rel of ['src/i18n/messages/en.ts', 'src/i18n/messages/zh-CN.ts']) {
      const src = source(rel)
      for (const key of ['queueContextWaitingCleanup:', 'waitingWorkspaceCleanup:']) {
        const line = src.split('\n').find((l) => l.includes(key)) ?? ''
        expect(line, `${rel} ${key}`).toContain('#{blockedBy}')
      }
    }
  })
})
