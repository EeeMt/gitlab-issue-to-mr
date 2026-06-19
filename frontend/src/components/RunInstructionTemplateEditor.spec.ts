import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

describe('RunInstructionTemplateEditor', () => {
  it('keeps variables compact, explains them, and replaces the current selection', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: 'Before selected after',
        availablePlaceholders: ['user_prompt', 'project_path']
      }
    })
    const picker = wrapper.find('details.run-instruction-editor__variables')
    expect(picker.attributes('open')).toBeUndefined()
    const pickerToggle = wrapper.get('[data-testid="variable-picker-toggle"]')
    expect(pickerToggle.text()).toContain(
      'runInstruction.insertVariable'
    )
    expect(pickerToggle.find('svg').exists()).toBe(true)
    expect(pickerToggle.text()).not.toContain('2')
    expect(wrapper.text()).toContain('runInstruction.placeholderDescriptions.user_prompt')
    expect(wrapper.text()).toContain('runInstruction.placeholderDescriptions.project_path')
    const userPromptVariable = wrapper.get('[data-placeholder="user_prompt"]')
    expect(userPromptVariable.get('code').text()).toBe('{{user_prompt}}')
    expect(userPromptVariable.get('.run-instruction-editor__variable-copy > span').text()).toBe(
      'runInstruction.placeholderDescriptions.user_prompt'
    )

    const textarea = wrapper.find('textarea').element as HTMLTextAreaElement
    textarea.setSelectionRange(7, 15)
    const pickerElement = picker.element as HTMLDetailsElement
    pickerElement.open = true
    await userPromptVariable.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([
      'Before {{user_prompt}} after'
    ])
    expect(pickerElement.open).toBe(false)
  })

  it('emits restore and preview actions', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{user_prompt}}',
        availablePlaceholders: ['user_prompt'],
        previewEnabled: true
      }
    })
    const buttons = wrapper.findAll('button')
    await buttons.find((button) => button.text().includes('runInstruction.restoreDefault'))!.trigger('click')
    await buttons.find((button) => button.text().includes('runInstruction.preview'))!.trigger('click')
    expect(wrapper.emitted('restore-default')).toHaveLength(1)
    expect(wrapper.emitted('preview')).toHaveLength(1)
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

  it('renders an expanded preview card that can be collapsed', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: '{{user_prompt}}',
        availablePlaceholders: ['user_prompt'],
        previewResult: 'Rendered result',
        previewError: 'Preview failed'
      }
    })
    expect(wrapper.text()).toContain('Rendered result')
    expect(wrapper.text()).toContain('Preview failed')
    expect(wrapper.get('[data-testid="preview-toggle"]').text()).toContain(
      'runInstruction.previewReady'
    )
    expect(wrapper.vm.previewExpanded).toBe(true)

    wrapper.vm.previewExpanded = false
    await wrapper.vm.$nextTick()
    expect(wrapper.find('details.run-instruction-editor__preview-card').attributes('open')).toBeUndefined()
  })
})
