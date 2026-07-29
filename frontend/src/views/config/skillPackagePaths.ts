export type SkillFilePathError =
  | 'blank'
  | 'tooLong'
  | 'invalid'
  | 'reserved'
  | 'duplicate'
  | 'fileDirectoryConflict'

export const MAX_SKILL_FILE_PATH_LENGTH = 240

function basicPathError(path: string): SkillFilePathError | null {
  if (!path || path !== path.trim()) return 'blank'
  if (path.length > MAX_SKILL_FILE_PATH_LENGTH) return 'tooLong'
  if (path.includes('\\') || path.includes('\0') || path.startsWith('/') || path.endsWith('/')) {
    return 'invalid'
  }
  const parts = path.split('/')
  if (parts.some(part => !part || part === '.' || part === '..')) return 'invalid'
  if (parts[0] === 'SKILL.md') return 'reserved'
  return null
}

export function getSkillFilePathErrors(paths: string[]): Map<number, SkillFilePathError> {
  const errors = new Map<number, SkillFilePathError>()
  const indicesByPath = new Map<string, number[]>()

  paths.forEach((path, index) => {
    const error = basicPathError(path)
    if (error) {
      errors.set(index, error)
      return
    }
    const indices = indicesByPath.get(path) ?? []
    indices.push(index)
    indicesByPath.set(path, indices)
  })

  for (const indices of indicesByPath.values()) {
    if (indices.length < 2) continue
    for (const index of indices) errors.set(index, 'duplicate')
  }

  for (const [path, indices] of indicesByPath) {
    const parts = path.split('/')
    for (let depth = 1; depth < parts.length; depth += 1) {
      const parentPath = parts.slice(0, depth).join('/')
      const parentIndices = indicesByPath.get(parentPath)
      if (!parentIndices) continue
      for (const index of [...indices, ...parentIndices]) {
        if (!errors.has(index)) errors.set(index, 'fileDirectoryConflict')
      }
    }
  }
  return errors
}

export function countSkillDirectories(paths: string[]): number {
  const directories = new Set<string>()
  for (const path of paths) {
    if (basicPathError(path)) continue
    const parts = path.split('/')
    for (let depth = 1; depth < parts.length; depth += 1) {
      directories.add(parts.slice(0, depth).join('/'))
    }
  }
  return directories.size
}
