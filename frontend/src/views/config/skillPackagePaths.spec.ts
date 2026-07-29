import { describe, expect, it } from 'vitest'

import {
  countSkillDirectories,
  getSkillFilePathErrors,
} from './skillPackagePaths'

describe('skillPackagePaths', () => {
  it('reports unsafe, duplicate, and file-directory-conflicting paths', () => {
    const paths = [
      '../secret.md',
      'references/guide.md',
      'references/guide.md',
      'scripts',
      'scripts/tools/check.sh',
    ]

    expect(Object.fromEntries(getSkillFilePathErrors(paths))).toEqual({
      0: 'invalid',
      1: 'duplicate',
      2: 'duplicate',
      3: 'fileDirectoryConflict',
      4: 'fileDirectoryConflict',
    })
  })

  it('counts each distinct directory represented by deeply nested files', () => {
    expect(countSkillDirectories([
      'references/api/v2/guide.md',
      'references/api/v2/schema.json',
      'scripts/tools/check.sh',
    ])).toBe(5)
  })
})
