import { flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import SkillSettingsPanel from './SkillSettingsPanel.vue'

const { api, messages } = vi.hoisted(() => ({
  api: {
    getAdminSkills: vi.fn(),
    getAdminSkill: vi.fn(),
    createSkill: vi.fn(),
    updateSkill: vi.fn(),
    setSkillEnabled: vi.fn(),
    deleteSkill: vi.fn(),
  },
  messages: { success: vi.fn(), error: vi.fn() },
}))

vi.mock('../../api', () => api)
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('naive-ui', () => ({
  useMessage: () => messages,
  NSpin: { setup: (_: unknown, { slots }: any) => () => h('div', slots.default?.()) },
  NCard: { setup: (_: unknown, { slots }: any) => () => h('div', [slots.header?.(), slots.default?.()]) },
  NForm: { setup: (_: unknown, { slots }: any) => () => h('form', slots.default?.()) },
  NFormItem: { setup: (_: unknown, { slots }: any) => () => h('label', [slots.default?.(), slots.feedback?.()]) },
  NInput: {
    props: ['value'],
    emits: ['update:value'],
    setup: (props: any, { emit }: any) => () => h('textarea', {
      value: props.value,
      onInput: (event: Event) => emit('update:value', (event.target as HTMLTextAreaElement).value),
    }),
  },
  NSwitch: {
    props: ['value'],
    emits: ['update:value'],
    setup: (props: any, { emit }: any) => () => h('button', {
      class: 'switch',
      onClick: () => emit('update:value', !props.value),
    }),
  },
  NButton: {
    props: ['disabled'],
    emits: ['click'],
    setup: (props: any, { emit, slots }: any) => () => h('button', {
      disabled: props.disabled,
      onClick: () => emit('click'),
    }, slots.default?.()),
  },
  NSpace: { setup: (_: unknown, { slots }: any) => () => h('div', slots.default?.()) },
  NTag: { setup: (_: unknown, { slots }: any) => () => h('span', slots.default?.()) },
}))

const skill = {
  id: 4,
  name: 'review-changes',
  description: 'Review the final changes.',
  skill_md: [
    '---',
    'name: review-changes',
    'description: Review the final changes.',
    'allowed-tools: Read Grep',
    'context: fork',
    '---',
    '',
    'Inspect the diff and report findings.',
    '',
  ].join('\n'),
  files: [
    {
      path: 'scripts/check.sh',
      content_base64: 'IyEvYmluL3NoCg==',
      executable: true,
    },
  ],
  enabled: true,
  created_at: '2026-07-28T00:00:00Z',
  updated_at: '2026-07-28T00:00:00Z',
}

describe('SkillSettingsPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.getAdminSkills.mockResolvedValue([skill])
    api.getAdminSkill.mockResolvedValue(skill)
    api.createSkill.mockResolvedValue(skill)
    api.updateSkill.mockResolvedValue(skill)
    api.setSkillEnabled.mockResolvedValue({ ...skill, enabled: false })
    api.deleteSkill.mockResolvedValue(undefined)
  })

  it('loads all skills and opens an existing skill for editing', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()

    expect(api.getAdminSkills).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('review-changes')
    await wrapper.find('.skill-settings__item').trigger('click')
    await flushPromises()
    expect(api.getAdminSkill).toHaveBeenCalledWith(4)
    expect(wrapper.text()).toContain('config.skills.editTitle')
    expect(wrapper.find('.skill-settings__file textarea').element.value).toBe('scripts/check.sh')
  })

  it('creates a skill from the editor', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('backend-review')
    await textareas[1].setValue('---\nname: backend-review\ndescription: Review backend changes.\n---\n\nInspect API and database behavior.\n')

    const saveButton = wrapper.findAll('button').find(button =>
      button.text().includes('config.saveChanges')
    )
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.createSkill).toHaveBeenCalledWith({
      name: 'backend-review',
      skill_md: '---\nname: backend-review\ndescription: Review backend changes.\n---\n\nInspect API and database behavior.\n',
      files: [],
      enabled: true,
    })
  })

  it('uploads a supporting file into the package payload', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('backend-review')
    await textareas[1].setValue('---\nname: backend-review\ndescription: Review backend changes.\n---\n\nInspect API and database behavior.\n')

    const input = wrapper.find('input[type="file"]')
    const file = new File(['# Guide\n'], 'guide.md', { type: 'text/markdown' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('.skill-settings__file').exists()).toBe(true)
    })

    const saveButton = wrapper.findAll('button').find(button =>
      button.text().includes('config.saveChanges')
    )
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.createSkill).toHaveBeenCalledWith(expect.objectContaining({
      files: [
        {
          path: 'guide.md',
          content_base64: 'IyBHdWlkZQo=',
          executable: false,
        },
      ],
    }))
  })

  it('preserves supporting package files when editing a skill', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('.skill-settings__item').trigger('click')
    await flushPromises()

    const saveButton = wrapper.findAll('button').find(button =>
      button.text().includes('config.saveChanges')
    )
    await saveButton?.trigger('click')
    await flushPromises()

    expect(api.updateSkill).toHaveBeenCalledWith(4, expect.objectContaining({
      skill_md: expect.stringContaining('allowed-tools: Read Grep'),
      files: [
        {
          path: 'scripts/check.sh',
          content_base64: 'IyEvYmluL3NoCg==',
          executable: true,
        },
      ],
    }))
  })

  it('imports a complete folder without dropping SKILL.md metadata', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const inputs = wrapper.findAll('input[type="file"]')
    const skillMd = new File([
      '---\nname: imported-skill\ndescription: Imported package.\nallowed-tools: Read Grep\ncontext: fork\n---\n\nRun the imported workflow.\n',
    ], 'SKILL.md', { type: 'text/markdown' })
    const script = new File(['#!/bin/sh\n'], 'check.sh', { type: 'text/x-shellscript' })
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'package-folder/SKILL.md',
      configurable: true,
    })
    Object.defineProperty(script, 'webkitRelativePath', {
      value: 'package-folder/scripts/check.sh',
      configurable: true,
    })
    Object.defineProperty(inputs[1].element, 'files', {
      value: [skillMd, script],
      configurable: true,
    })
    await inputs[1].trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('.skill-settings__file').exists()).toBe(true)
    })

    const textareas = wrapper.findAll('textarea')
    expect(textareas[0].element.value).toBe('imported-skill')
    expect(textareas[1].element.value).toContain('allowed-tools: Read Grep')
    expect(textareas[1].element.value).toContain('context: fork')

    const saveButton = wrapper.findAll('button').find(button =>
      button.text().includes('config.saveChanges')
    )
    await saveButton?.trigger('click')
    await flushPromises()
    expect(api.createSkill).toHaveBeenCalledWith(expect.objectContaining({
      name: 'imported-skill',
      skill_md: expect.stringContaining('allowed-tools: Read Grep'),
      files: [expect.objectContaining({ path: 'scripts/check.sh', executable: true })],
    }))
  })

  it('keeps the existing draft unchanged when a folder import fails', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const textareas = wrapper.findAll('textarea')
    await textareas[0].setValue('existing-skill')
    await textareas[1].setValue(
      '---\nname: existing-skill\ndescription: Existing package.\n---\n\nKeep this draft.\n',
    )

    const inputs = wrapper.findAll('input[type="file"]')
    const skillMd = new File([
      '---\nname: imported-skill\ndescription: Imported package.\n---\n\nReplace the draft.\n',
    ], 'SKILL.md', { type: 'text/markdown' })
    const oversized = new File(['x'], 'too-large.sh', { type: 'text/x-shellscript' })
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'package-folder/SKILL.md',
      configurable: true,
    })
    Object.defineProperty(oversized, 'webkitRelativePath', {
      value: 'package-folder/scripts/too-large.sh',
      configurable: true,
    })
    Object.defineProperty(oversized, 'size', {
      value: 2 * 1024 * 1024 + 1,
      configurable: true,
    })
    Object.defineProperty(inputs[1].element, 'files', {
      value: [skillMd, oversized],
      configurable: true,
    })

    await inputs[1].trigger('change')
    await vi.waitFor(() => expect(messages.error).toHaveBeenCalledOnce())

    expect(textareas[0].element.value).toBe('existing-skill')
    expect(textareas[1].element.value).toContain('Keep this draft.')
    expect(wrapper.find('.skill-settings__file').exists()).toBe(false)
  })
})
