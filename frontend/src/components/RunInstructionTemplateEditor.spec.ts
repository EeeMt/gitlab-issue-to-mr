import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

describe('RunInstructionTemplateEditor', () => {
  it('uses a non-resizable fixed-height textarea when fixed rows are provided', () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{user_prompt}}',
        availablePlaceholders: ['user_prompt'],
        fixedRows: 12
      }
    })

    expect(wrapper.get('textarea').attributes('rows')).toBe('12')
    expect(wrapper.get('.n-input').classes()).not.toContain('n-input--autosize')
    expect(wrapper.get('.n-input').classes()).not.toContain('n-input--resizable')
  })

  it('can hide prompt-only while keeping restore-default available', () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{issue_title}}',
        availablePlaceholders: ['issue_title'],
        hidePromptOnly: true
      }
    })

    const actionLabels = wrapper
      .findAll('.run-instruction-editor__actions button')
      .map((button) => button.text())
    expect(actionLabels).toEqual(['runInstruction.restoreDefault'])
  })

  it('keeps variables compact, explains them, and replaces the current selection', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      attachTo: document.body,
      props: {
        modelValue: 'Before selected after',
        availablePlaceholders: ['user_prompt', 'project_path']
      }
    })
    const pickerToggle = wrapper.get('[data-testid="variable-picker-toggle"]')
    expect(pickerToggle.attributes('aria-expanded')).toBe('false')
    expect(pickerToggle.text()).toContain(
      'runInstruction.insertVariable'
    )
    expect(pickerToggle.find('svg').exists()).toBe(true)
    expect(pickerToggle.text()).not.toContain('2')
    expect(wrapper.find('.run-instruction-editor__variables-panel').exists()).toBe(false)

    await pickerToggle.trigger('click')
    const variablePanel = document.body.querySelector('.run-instruction-editor__variables-panel')
    expect(variablePanel).not.toBeNull()
    expect(variablePanel?.textContent).toContain('runInstruction.placeholderDescriptions.user_prompt')
    expect(variablePanel?.textContent).toContain('runInstruction.placeholderDescriptions.project_path')
    const userPromptVariable = variablePanel?.querySelector(
      '[data-placeholder="user_prompt"]'
    ) as HTMLButtonElement
    expect(userPromptVariable.querySelector('code')?.textContent).toBe('{{user_prompt}}')
    expect(userPromptVariable.querySelector('.run-instruction-editor__variable-copy > span')?.textContent).toBe(
      'runInstruction.placeholderDescriptions.user_prompt'
    )

    const textarea = wrapper.find('textarea').element as HTMLTextAreaElement
    textarea.setSelectionRange(7, 15)
    userPromptVariable.click()
    await wrapper.vm.$nextTick()
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([
      'Before {{user_prompt}} after'
    ])
    expect(pickerToggle.attributes('aria-expanded')).toBe('false')
    wrapper.unmount()
  })

  it('restores the default and generates the preview on first expansion', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{user_prompt}}',
        availablePlaceholders: ['user_prompt'],
        previewEnabled: true
      }
    })
    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text().includes('runInstruction.restoreDefault'))!.trigger('click')
    expect(wrapper.emitted('restore-default')).toHaveLength(1)

    const previewCard = wrapper.get('details.run-instruction-editor__preview-card')
    expect(previewCard.attributes('open')).toBeUndefined()
    ;(previewCard.element as HTMLDetailsElement).open = true
    await previewCard.trigger('toggle')
    expect(wrapper.emitted('preview')).toHaveLength(1)
    expect(wrapper.vm.previewExpanded).toBe(true)
  })

  it('shows unknown-placeholder and missing-requirement feedback', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{unknown}}',
        availablePlaceholders: ['user_prompt']
      }
    })
    expect(wrapper.text()).toContain('runInstruction.unknownPlaceholders')
    await wrapper.setProps({ modelValue: 'literal instruction' })
    expect(wrapper.text()).toContain('runInstruction.userPromptMissing')
  })

  it('keeps the preview card collapsed by default and refreshes in place', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{user_prompt}}',
        availablePlaceholders: ['user_prompt'],
        previewEnabled: true,
        previewResult: 'Rendered result',
        previewError: 'Preview failed'
      }
    })
    expect(wrapper.text()).toContain('Rendered result')
    expect(wrapper.text()).toContain('Preview failed')
    expect(wrapper.get('[data-testid="preview-toggle"]').text()).toBe(
      'runInstruction.preview›'
    )
    expect(wrapper.find('[data-testid="preview-action"]').exists()).toBe(false)
    expect(wrapper.text()).not.toContain('runInstruction.previewReady')
    expect(wrapper.vm.previewExpanded).toBe(false)
    expect(wrapper.find('details.run-instruction-editor__preview-card').attributes('open')).toBeUndefined()

    const previewCard = wrapper.get('details.run-instruction-editor__preview-card')
    ;(previewCard.element as HTMLDetailsElement).open = true
    await previewCard.trigger('toggle')
    expect(wrapper.emitted('preview')).toBeUndefined()
    expect(wrapper.vm.previewExpanded).toBe(true)
    await wrapper.get('[data-testid="preview-refresh"]').trigger('click')
    expect(wrapper.emitted('preview')).toHaveLength(1)
    expect(wrapper.vm.previewExpanded).toBe(true)

    ;(previewCard.element as HTMLDetailsElement).open = false
    await previewCard.trigger('toggle')
    expect(wrapper.vm.previewExpanded).toBe(false)
  })
})
