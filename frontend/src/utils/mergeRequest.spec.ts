import { describe, expect, it } from 'vitest'
import {
  getMergeRequestLabel,
  sanitizeMergeRequestTitle,
  getCommitMessageLabel,
  sanitizeCommitMessage,
} from './mergeRequest'

describe('sanitizeCommitMessage', () => {
  it('removes completed think blocks', () => {
    expect(sanitizeCommitMessage('<think>reasoning</think>feat: 修复 Git 配置')).toBe('feat: 修复 Git 配置')
  })

  it('drops messages that start with an unclosed think block', () => {
    expect(sanitizeCommitMessage('<think>用户要求输出一个标题')).toBe('')
  })

  it('preserves internal newlines (multi-line commit message)', () => {
    const msg = 'feat: add login\n\n- update auth module\n\nAI-Generated: true'
    expect(sanitizeCommitMessage(msg)).toBe(msg)
  })

  it('returns empty string for null/undefined', () => {
    expect(sanitizeCommitMessage(null)).toBe('')
    expect(sanitizeCommitMessage(undefined)).toBe('')
  })
})

describe('getCommitMessageLabel', () => {
  it('returns the first line of a multi-line commit message', () => {
    expect(getCommitMessageLabel({
      commit_message: 'feat: 实现用户认证\n\n- 更新 auth 模块\n\nAI-Generated: true',
    })).toBe('feat: 实现用户认证')
  })

  it('returns the full message when single-line', () => {
    expect(getCommitMessageLabel({ commit_message: 'fix: 修复登录问题' })).toBe('fix: 修复登录问题')
  })

  it('falls back to MR IID when commit_message is not displayable', () => {
    expect(getCommitMessageLabel({
      commit_message: '<think>未完成的思考',
      issue: { merge_request_iid: 42 },
    })).toBe('!42')
  })

  it('uses stable fallback when there is no message or IID', () => {
    expect(getCommitMessageLabel({ commit_message: null, issue: { merge_request_iid: null } })).toBe('Merge Request')
  })

  it('accepts custom fallback text', () => {
    expect(getCommitMessageLabel({ commit_message: null }, 'Open MR')).toBe('Open MR')
  })
})

// --- Deprecated alias backward-compat ---
describe('deprecated aliases (backward compat)', () => {
  it('sanitizeMergeRequestTitle still strips think blocks', () => {
    expect(sanitizeMergeRequestTitle('<think>reasoning</think>修复 Git 配置')).toBe('修复 Git 配置')
  })

  it('sanitizeMergeRequestTitle drops unclosed think blocks', () => {
    expect(sanitizeMergeRequestTitle('<think>用户要求输出一个 GitLab Merge Request 标题')).toBe('')
  })

  it('getMergeRequestLabel falls back to MR IID when title is not displayable', () => {
    expect(getMergeRequestLabel({
      merge_request_title: '<think>用户要求输出一个 GitLab Merge Request 标题',
      issue: { merge_request_iid: 297, merge_request_url: 'https://gitlab.example/mr/297' },
    })).toBe('!297')
  })

  it('getMergeRequestLabel uses stable fallback when there is no title or IID', () => {
    expect(getMergeRequestLabel({ merge_request_title: null, issue: { merge_request_iid: null } })).toBe('Merge Request')
  })
})
