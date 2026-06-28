import { execFileSync } from 'node:child_process'

export function resolveGitCommit(): string {
  const commitFromEnvironment = process.env.GIT_COMMIT || process.env.CI_COMMIT_SHA
  if (commitFromEnvironment) return commitFromEnvironment

  try {
    return execFileSync('git', ['rev-parse', 'HEAD'], {
      encoding: 'utf8',
    }).trim()
  } catch {
    return 'unknown'
  }
}

export function gitCommitDefine(): Record<string, string> {
  return {
    __GIT_COMMIT__: JSON.stringify(resolveGitCommit()),
  }
}
