import { describe, expect, it } from 'vitest'
import { getMergeRequestLabel, sanitizeMergeRequestTitle } from './mergeRequest'

describe('merge request display utilities', () => {
  it('removes completed think blocks from titles', () => {
    expect(sanitizeMergeRequestTitle('<think>reasoning</think>修复 Git 配置')).toBe('修复 Git 配置')
  })

  it('drops titles that start with an unclosed think block', () => {
    expect(sanitizeMergeRequestTitle('<think>用户要求输出一个 GitLab Merge Request 标题')).toBe('')
  })

  it('falls back to MR IID when title is not displayable', () => {
    expect(getMergeRequestLabel({
      merge_request_title: '<think>用户要求输出一个 GitLab Merge Request 标题',
      issue: { merge_request_iid: 297, merge_request_url: 'https://gitlab.example/mr/297' }
    })).toBe('!297')
  })

  it('uses a stable fallback when there is no title or IID', () => {
    expect(getMergeRequestLabel({ merge_request_title: null, issue: { merge_request_iid: null } })).toBe('Merge Request')
  })
})
