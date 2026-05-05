type MergeRequestLabelTask = {
  merge_request_title?: string | null
  issue?: {
    merge_request_iid?: number | null
    merge_request_url?: string | null
  } | null
}

const THINK_BLOCK_RE = /<think\b[^>]*>[\s\S]*?<\/think>/gi
const OPEN_THINK_RE = /^<think\b[^>]*>/i

export function sanitizeMergeRequestTitle(title?: string | null): string {
  if (!title) return ''

  const cleaned = title
    .replace(THINK_BLOCK_RE, '')
    .replace(/\s+/g, ' ')
    .trim()

  if (OPEN_THINK_RE.test(cleaned)) return ''
  return cleaned
}

export function getMergeRequestLabel(task: MergeRequestLabelTask, fallback = 'Merge Request'): string {
  const title = sanitizeMergeRequestTitle(task.merge_request_title)
  if (title) return title

  const iid = task.issue?.merge_request_iid
  if (iid != null) return `!${iid}`

  return fallback
}
