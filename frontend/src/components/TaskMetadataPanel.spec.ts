import { describe, expect, it } from 'vitest'
import taskMetadataPanelSource from './TaskMetadataPanel.vue?raw'
import taskRuntimeSummaryRowsSource from './TaskRuntimeSummaryRows.vue?raw'

describe('TaskMetadataPanel', () => {
  it('aligns metadata values after the widest field label', () => {
    expect(taskMetadataPanelSource).toContain('grid-template-columns: max-content minmax(0, 1fr);')
    expect(taskMetadataPanelSource).toContain('display: contents;')
    expect(taskMetadataPanelSource).toContain(`.metadata-body {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 10px;
  row-gap: 12px;
  align-items: center;
}`)
    expect(taskMetadataPanelSource).not.toContain(`.metadata-body {
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  column-gap: 12px;
  row-gap: 14px;
  align-items: baseline;
}`)
    expect(taskMetadataPanelSource).not.toContain('min-width: 90px;')
  })

  it('uses the same compact reference style for project and source links', () => {
    expect(taskMetadataPanelSource).toContain('class="app-link metadata-reference-link project-reference-link"')
    expect(taskMetadataPanelSource).toContain('class="app-link metadata-reference-link task-issue-link"')
    expect(taskMetadataPanelSource).toContain('.metadata-reference-link {')
    expect(taskMetadataPanelSource).toContain('flex: 0 1 auto;')
    expect(taskMetadataPanelSource).toContain('width: fit-content;')
    expect(taskMetadataPanelSource).toContain('border-bottom: 1px solid color-mix(')
    expect(taskMetadataPanelSource).not.toContain('flex: 1 1 auto;')
    expect(taskMetadataPanelSource).not.toContain('--task-issue-link-color')
    expect(taskMetadataPanelSource).toContain('font-weight: 400;')
    expect(taskMetadataPanelSource).toContain('.task-issue-link__id {\n  flex: 0 0 auto;\n  font-family: var(--n-font-family-mono, \'JetBrains Mono\', monospace);\n  font-size: 12px;\n  font-weight: 500;')
  })

  it('keeps long values inside the metadata column and summarizes runtime services in popovers', () => {
    expect(taskMetadataPanelSource).toContain('<TaskRuntimeSummaryRows :task="task" />')
    expect(taskRuntimeSummaryRowsSource).toContain('class="metadata-summary-trigger metadata-summary-trigger--provider"')
    expect(taskRuntimeSummaryRowsSource).toContain('class="metadata-summary-trigger metadata-summary-trigger--worker"')
    expect(taskRuntimeSummaryRowsSource).toContain('data-testid="provider-summary-popover"')
    expect(taskRuntimeSummaryRowsSource).toContain('data-testid="worker-summary-popover"')
    expect(taskRuntimeSummaryRowsSource).toContain(':show="providerPopoverVisible"')
    expect(taskRuntimeSummaryRowsSource).toContain(':show="workerPopoverVisible"')
    expect(taskRuntimeSummaryRowsSource.match(/\n        scrollable\n/g)).toHaveLength(2)
    expect(taskRuntimeSummaryRowsSource).not.toContain('overflow-y: auto;')
    expect(taskRuntimeSummaryRowsSource).toContain(':placement="providerPopoverLayout.placement"')
    expect(taskRuntimeSummaryRowsSource).toContain(':placement="workerPopoverLayout.placement"')
    expect(taskRuntimeSummaryRowsSource).toContain('resolveRuntimePopoverLayout(providerTriggerRef.value)')
    expect(taskRuntimeSummaryRowsSource).toContain('resolveRuntimePopoverLayout(workerTriggerRef.value)')
    expect(taskRuntimeSummaryRowsSource).toContain('getTaskModelServiceSummary')
    expect(taskRuntimeSummaryRowsSource).toContain('getTaskWorkerRuntimeSummary')
    expect(taskRuntimeSummaryRowsSource).toContain('providerSummary.system_prompt')
    expect(taskRuntimeSummaryRowsSource).toContain('workerSummary.environment_variables')
    expect(taskRuntimeSummaryRowsSource).toContain("configuration_source === 'execution_snapshot'")
    expect(taskRuntimeSummaryRowsSource).not.toContain('sessionMode')
    expect(taskRuntimeSummaryRowsSource).not.toContain('task.container_name || task.container_id')
    expect(taskRuntimeSummaryRowsSource).not.toContain('formatTokenValue')
    expect(taskMetadataPanelSource).toContain('overflow-wrap: anywhere;')
    expect(taskRuntimeSummaryRowsSource).toContain('text-overflow: ellipsis;')
    expect(taskRuntimeSummaryRowsSource).toContain('grid-template-columns: 1fr;')
  })

  it('shows the harness engine used by the task in the overview', () => {
    expect(taskMetadataPanelSource).toContain('v-if="task.harness_key"')
    expect(taskMetadataPanelSource).toContain("t('taskView.harness')")
    expect(taskMetadataPanelSource).toContain('taskView.harnessCodex')
    expect(taskMetadataPanelSource).toContain('taskView.harnessClaude')
    expect(taskMetadataPanelSource).toContain("task.harness_key === 'codex'")
  })

  it('keeps label icons aligned and evenly spaced across the panel and runtime rows', () => {
    expect(taskMetadataPanelSource).toContain('.metadata-label {\n  display: inline-flex;\n  align-items: center;\n  gap: 4px;')
    expect(taskRuntimeSummaryRowsSource).toContain('.metadata-label {\n  display: inline-flex;\n  align-items: center;\n  gap: 4px;')
    expect(taskMetadataPanelSource).toContain('.metadata-label-icon {\n  flex: 0 0 auto;\n  opacity: 0.65;')
    expect(taskRuntimeSummaryRowsSource).toContain('.metadata-label-icon {\n  flex: 0 0 auto;\n  opacity: 0.65;')
  })

  it('renders task mode as a chip with the same mode icons used by task creation', () => {
    expect(taskMetadataPanelSource).toContain('CodeSlashOutline')
    expect(taskMetadataPanelSource).toContain('BulbOutline')
    expect(taskMetadataPanelSource).toContain('<span class="task-mode-chip" :class="taskModeMeta.modifierClass">')
    expect(taskMetadataPanelSource).toContain('taskModeMeta.icon')
    expect(taskMetadataPanelSource).toContain("modifierClass: isPlan ? 'task-mode-chip--plan' : 'task-mode-chip--execute'")
    expect(taskMetadataPanelSource).toContain('.task-mode-chip--execute {')
    expect(taskMetadataPanelSource).toContain('.task-mode-chip--plan {')
  })

  it('renders branch configuration as a labeled vertical flow', () => {
    expect(taskMetadataPanelSource).toContain('class="branch-flow__stage"')
    expect(taskMetadataPanelSource).toContain("t('taskView.branchBase')")
    expect(taskMetadataPanelSource).toContain("t('taskView.branchWork')")
    expect(taskMetadataPanelSource).toContain("t('taskView.branchTarget')")
    expect(taskMetadataPanelSource).toContain('.branch-flow::before {')
    expect(taskMetadataPanelSource).not.toContain('class="branch-arrow"')
  })

  it('renders timeline values on a compact vertical track', () => {
    expect(taskMetadataPanelSource).toContain('class="time-point__marker"')
    expect(taskMetadataPanelSource).toContain('class="time-point__content"')
    expect(taskMetadataPanelSource).toContain('<time class="time-point__value" :datetime="task.created_at">')
    expect(taskMetadataPanelSource).toContain('.time-axis::before {')
    expect(taskMetadataPanelSource).toContain('.time-point__marker {\n  z-index: 1;\n  box-sizing: border-box;')
    expect(taskMetadataPanelSource).not.toContain('class="time-axis__sep"')
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

	  it('shows non-manual trigger sources beside the source row', () => {
	    expect(taskMetadataPanelSource).toContain('triggerSourceMeta')
	    expect(taskMetadataPanelSource).toContain('task.trigger_source')
	    expect(taskMetadataPanelSource).toContain("ci_auto_repair: 'error'")
	    expect(taskMetadataPanelSource).toContain("t(`taskView.triggerSource.${source}`)")
	    expect(taskMetadataPanelSource).toContain('class="trigger-source-tag"')
	  })
	})
