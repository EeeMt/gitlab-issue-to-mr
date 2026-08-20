import { describe, expect, it } from 'vitest'

import en from './en'
import zhCN from './zh-CN'

describe('common messages', () => {
  it('translates unavailable in both supported locales', () => {
    expect(en.common.unavailable).toBe('Unavailable')
    expect(zhCN.common.unavailable).toBe('不可用')
  })
})
