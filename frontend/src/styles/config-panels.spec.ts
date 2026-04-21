import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const cssSource = readFileSync(resolve(process.cwd(), 'src/styles/config-panels.css'), 'utf8')

describe('config-panels modal styling', () => {
  it('targets the config editor modal root element directly', () => {
    expect(cssSource).toMatch(/\.config-editor-modal\s*\{/)
  })
})
