import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

import { describe, expect, it } from 'vitest'

const promptTemplatesPanelSource = readFileSync(
  resolve(process.cwd(), 'src/views/config/PromptTemplatesPanel.vue'),
  'utf8'
)
const mattermostPanelSource = readFileSync(
  resolve(process.cwd(), 'src/components/config/MattermostNotificationsPanel.vue'),
  'utf8'
)
const configPanelsCssSource = readFileSync(
  resolve(process.cwd(), 'src/styles/config-panels.css'),
  'utf8'
)

describe('config modal layout polish', () => {
  it('removes the nested prompt template editor shell from the modal body', () => {
    expect(promptTemplatesPanelSource).not.toContain('class="prompt-template-editor"')
  })

  it('defines a scrollable body wrapper for tall config editor modals', () => {
    expect(mattermostPanelSource).toContain('class="config-editor-modal__scroll"')
    expect(configPanelsCssSource).toContain('.config-editor-modal__scroll')
  })
})
