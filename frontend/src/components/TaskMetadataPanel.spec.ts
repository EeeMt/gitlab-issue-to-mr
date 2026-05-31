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

  it('renders initiator as a dedicated metadata row guarded by v-if', () => {
    // The initiator_username must be on a separate row with its own v-if guard
    expect(taskMetadataPanelSource).toContain('v-if="task.initiator_username"')
    // The old inline .metadata-initiator CSS class must no longer exist
    expect(taskMetadataPanelSource).not.toContain('.metadata-initiator')
  })

  it('source row does not contain an inline initiator suffix', () => {
    // The .metadata-initiator class must not appear anywhere in the template
    expect(taskMetadataPanelSource).not.toContain('metadata-initiator')
  })
})
