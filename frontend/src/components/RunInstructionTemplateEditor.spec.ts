import { describe, expect, it, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import RunInstructionTemplateEditor from './RunInstructionTemplateEditor.vue'

vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key })
}))

describe('RunInstructionTemplateEditor', () => {
  it('renders placeholder chips and replaces the current selection', async () => {
    const wrapper = mount(RunInstructionTemplateEditor, {
      props: {
        modelValue: 'Before selected after',
        availablePlaceholders: ['user_prompt']
      }
    })
    const textarea = wrapper.find('textarea').element as HTMLTextAreaElement
    textarea.setSelectionRange(7, 15)
    const chip = wrapper.findAll('button').find((button) => button.text().includes('{{user_prompt}}'))
    await chip!.trigger('click')
    expect(wrapper.emitted('update:modelValue')?.at(-1)).toEqual([
      'Before {{user_prompt}} after'
    ])
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

  it('renders preview content and preview errors', () => {
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
  })
})
