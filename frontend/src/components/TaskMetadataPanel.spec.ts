import { describe, expect, it } from 'vitest'
import taskMetadataPanelSource from './TaskMetadataPanel.vue?raw'

describe('TaskMetadataPanel', () => {
  it('aligns metadata values after the widest field label', () => {
    expect(taskMetadataPanelSource).toContain('grid-template-columns: max-content minmax(0, 1fr);')
    expect(taskMetadataPanelSource).toContain('display: contents;')
    expect(taskMetadataPanelSource).not.toContain('min-width: 90px;')
  })

  it('styles the issue link as a prominent chip', () => {
    expect(taskMetadataPanelSource).toContain('class="app-link task-issue-link"')
    expect(taskMetadataPanelSource).toContain('.task-issue-link {')
    expect(taskMetadataPanelSource).toContain('--task-issue-link-color: #3b82f6;')
    expect(taskMetadataPanelSource).toContain('border-radius: 999px;')
    expect(taskMetadataPanelSource).toContain('font-weight: 400;')
    expect(taskMetadataPanelSource).toContain('.task-issue-link__id {\n  flex: 0 0 auto;\n  font-family: var(--n-font-family-mono, \'JetBrains Mono\', monospace);\n  font-size: 12px;\n  font-weight: 500;')
  })
})
