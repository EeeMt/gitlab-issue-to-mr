type CommitMessageTask = {
  commit_message?: string | null
  issue?: {
    merge_request_iid?: number | null
    merge_request_url?: string | null
  } | null
}

const THINK_BLOCK_RE = /<think\b[^>]*>[\s\S]*?<\/think>/gi
const OPEN_THINK_RE = /^<think\b[^>]*>/i

export function sanitizeCommitMessage(message?: string | null): string {
  if (!message) return ''

  const cleaned = message
    .replace(THINK_BLOCK_RE, '')
    .trim()

  if (OPEN_THINK_RE.test(cleaned)) return ''
  return cleaned
}

/** Returns the first (subject) line of the commit message for use as a label. */
export function getCommitMessageLabel(task: CommitMessageTask, fallback = 'Merge Request'): string {
  const message = sanitizeCommitMessage(task.commit_message)
  if (message) return message.split('\n')[0].trim() || fallback

  const iid = task.issue?.merge_request_iid
  if (iid != null) return `!${iid}`

  return fallback
}

// --- Backward-compat aliases (prefer the new names above) ---

/** @deprecated Use CommitMessageTask */
export type MergeRequestLabelTask = CommitMessageTask & { merge_request_title?: string | null }

/** @deprecated Use sanitizeCommitMessage */
export function sanitizeMergeRequestTitle(title?: string | null): string {
  return sanitizeCommitMessage(title)
}

/** @deprecated Use getCommitMessageLabel */
export function getMergeRequestLabel(task: MergeRequestLabelTask, fallback = 'Merge Request'): string {
  return getCommitMessageLabel({ ...task, commit_message: task.commit_message ?? task.merge_request_title }, fallback)
}
