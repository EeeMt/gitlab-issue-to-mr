import { enableAutoUnmount, flushPromises, mount } from '@vue/test-utils'
import { h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import SkillSettingsPanel from './SkillSettingsPanel.vue'

enableAutoUnmount(afterEach)
afterEach(() => {
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

const { api, dialogs, messages, routeState } = vi.hoisted(() => ({
  api: {
    getAdminSkills: vi.fn(),
    getAdminSkill: vi.fn(),
    downloadSkill: vi.fn(),
    createSkill: vi.fn(),
    updateSkill: vi.fn(),
    deleteSkill: vi.fn(),
  },
  dialogs: { warning: vi.fn() },
  messages: { success: vi.fn(), error: vi.fn() },
  routeState: { leaveGuard: null as null | (() => boolean | Promise<boolean>) },
}))

vi.mock('../../api', () => api)
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (key: string) => key }),
}))
vi.mock('vue-router', () => ({
  onBeforeRouteLeave: (guard: () => boolean | Promise<boolean>) => {
    routeState.leaveGuard = guard
  },
}))
vi.mock('naive-ui', () => ({
  useDialog: () => dialogs,
  useMessage: () => messages,
  NSpin: { setup: (_: unknown, { slots }: any) => () => h('div', slots.default?.()) },
  NCard: { setup: (_: unknown, { slots }: any) => () => h('div', [slots.header?.(), slots.default?.()]) },
  NEllipsis: {
    inheritAttrs: false,
    setup: (_: unknown, { attrs, slots }: any) => () => h('span', {
      ...attrs,
      class: ['n-ellipsis', attrs.class],
    }, [
      h('span', { class: 'n-ellipsis-trigger' }, slots.default?.()),
      h('span', { class: 'n-ellipsis-tooltip' }, slots.tooltip?.()),
    ]),
  },
  NForm: { setup: (_: unknown, { slots }: any) => () => h('form', slots.default?.()) },
  NFormItem: { setup: (_: unknown, { slots }: any) => () => h('label', [slots.default?.(), slots.feedback?.()]) },
  NInput: {
    inheritAttrs: false,
    props: ['value', 'type'],
    emits: ['update:value'],
    setup: (props: any, { attrs, emit }: any) => () => h(props.type === 'textarea' ? 'textarea' : 'input', {
      class: attrs.class,
      'data-testid': attrs['data-testid'],
      value: props.value,
      onInput: (event: Event) => emit('update:value', (event.target as HTMLTextAreaElement).value),
    }),
  },
  NIcon: { setup: () => () => h('span') },
  NPopconfirm: {
    emits: ['positive-click'],
    setup: (_: unknown, { emit, slots }: any) => () => h('div', [
      slots.trigger?.(),
      slots.default?.(),
      h('button', { class: 'popconfirm-positive', onClick: () => emit('positive-click') }),
    ]),
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
    routeState.leaveGuard = null
    api.getAdminSkills.mockResolvedValue([skill])
    api.getAdminSkill.mockResolvedValue(skill)
    api.downloadSkill.mockResolvedValue(new Blob(['archive']))
    api.createSkill.mockResolvedValue(skill)
    api.updateSkill.mockResolvedValue(skill)
    api.deleteSkill.mockResolvedValue(undefined)
  })

  it('loads all skills and opens an existing skill for editing', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()

    expect(api.getAdminSkills).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain('review-changes')
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()
    expect(api.getAdminSkill).toHaveBeenCalledWith(4)
    expect(wrapper.text()).toContain('config.skills.editMode')
    expect(wrapper.find('.skill-settings__file input').element.value).toBe('scripts/check.sh')
  })

  it('keeps the current draft when loading another skill fails', async () => {
    const otherSkill = {
      ...skill,
      id: 5,
      name: 'release-notes',
      description: 'Prepare release notes.',
    }
    api.getAdminSkills.mockResolvedValue([skill, otherSkill])
    api.getAdminSkill.mockImplementation((skillId: number) => {
      if (skillId === skill.id) return Promise.resolve(skill)
      return Promise.reject(new Error('detail unavailable'))
    })
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="skill-list-item-5"]').trigger('click')
    await flushPromises()

    expect(messages.error).toHaveBeenCalledWith('config.loadError')
    expect(wrapper.find('[data-testid="skill-list-item-4"]').attributes('aria-current')).toBe('true')
    expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('review-changes')
    expect(wrapper.find('.skill-settings__file input').element.value).toBe('scripts/check.sh')
  })

  it('filters the skill catalog by name or description', async () => {
    api.getAdminSkills.mockResolvedValue([
      skill,
      { ...skill, id: 5, name: 'release-notes', description: 'Prepare a changelog.' },
    ])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()

    await wrapper.find('[data-testid="skill-search-input"]').setValue('changelog')

    expect(wrapper.find('[data-testid="skill-list-item-4"]').exists()).toBe(false)
    expect(wrapper.find('[data-testid="skill-list-item-5"]').exists()).toBe(true)
  })

  it('provides the complete skill name through the overflow tooltip', async () => {
    const longName = 'review-complex-cross-service-configuration-changes'
    api.getAdminSkills.mockResolvedValue([{ ...skill, name: longName }])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()

    const name = wrapper.find('[data-testid="skill-name-4"]')
    expect(name.find('.n-ellipsis-trigger').text()).toBe(longName)
    expect(name.find('.n-ellipsis-tooltip').text()).toBe(longName)
  })

  it('exposes dirty state and resets the current draft', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()

    expect((wrapper.vm as any).hasUnsavedChanges()).toBe(false)
    await wrapper.find('[data-testid="skill-name-input"]').setValue('draft-skill')
    expect((wrapper.vm as any).hasUnsavedChanges()).toBe(true)

    await wrapper.find('[data-testid="skill-reset-button"]').trigger('click')
    expect((wrapper.vm as any).hasUnsavedChanges()).toBe(false)
  })

  it('asks before discarding an edited draft when switching modes', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="skill-name-input"]').setValue('edited-name')

    await wrapper.find('[data-testid="skill-create-button"]').trigger('click')

    expect(dialogs.warning).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('edited-name')

    dialogs.warning.mock.calls[0][0].onPositiveClick()
    await flushPromises()
    expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('')
    expect(wrapper.text()).toContain('config.skills.createMode')
  })

  it('guards route navigation while the draft has unsaved changes', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-name-input"]').setValue('draft-skill')

    expect(routeState.leaveGuard).not.toBeNull()
    const blockedNavigation = routeState.leaveGuard?.()
    expect(dialogs.warning).toHaveBeenCalledOnce()
    dialogs.warning.mock.calls[0][0].onNegativeClick()
    await expect(blockedNavigation).resolves.toBe(false)

    const allowedNavigation = routeState.leaveGuard?.()
    dialogs.warning.mock.calls[1][0].onPositiveClick()
    await expect(allowedNavigation).resolves.toBe(true)
  })

  it('guards browser unload and removes the listener when unmounted', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-name-input"]').setValue('draft-skill')

    const unloadEvent = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(unloadEvent)
    expect(unloadEvent.defaultPrevented).toBe(true)

    wrapper.unmount()
    const eventAfterUnmount = new Event('beforeunload', { cancelable: true })
    window.dispatchEvent(eventAfterUnmount)
    expect(eventAfterUnmount.defaultPrevented).toBe(false)
  })

  it('creates a skill from the editor', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const skillMarkdown = '---\nname: backend-review\ndescription: Review backend changes.\n---\n\nInspect API and database behavior.\n'
    api.createSkill.mockResolvedValue({
      ...skill,
      id: 6,
      name: 'backend-review',
      description: 'Review backend changes.',
      skill_md: skillMarkdown,
      files: [],
    })
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-name-input"]').setValue('backend-review')
    await wrapper.find('[data-testid="skill-markdown-input"]').setValue(skillMarkdown)

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()

    expect(api.createSkill).toHaveBeenCalledWith({
      name: 'backend-review',
      skill_md: skillMarkdown,
      files: [],
      enabled: true,
    })
    expect(api.getAdminSkills).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-testid="skill-list-item-6"]').exists()).toBe(true)
  })

  it('removes a deleted skill from the catalog without a second list request', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    await wrapper.find('.popconfirm-positive').trigger('click')
    await flushPromises()

    expect(api.deleteSkill).toHaveBeenCalledWith(4)
    expect(api.getAdminSkills).toHaveBeenCalledOnce()
    expect(wrapper.find('[data-testid="skill-list-item-4"]').exists()).toBe(false)
    expect(wrapper.text()).toContain('config.skills.createMode')
  })

  it('downloads the selected skill as a named ZIP archive', async () => {
    const blob = new Blob(['archive'])
    api.downloadSkill.mockResolvedValue(blob)
    const createObjectURL = vi.fn(() => 'blob:skill-package')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { createObjectURL, revokeObjectURL })
    let downloadedName = ''
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
      downloadedName = this.download
    })
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    await wrapper.find('[data-testid="skill-download-button"]').trigger('click')
    await flushPromises()

    expect(api.downloadSkill).toHaveBeenCalledWith(4)
    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalledOnce()
    expect(downloadedName).toBe('review-changes.zip')
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:skill-package')

    await wrapper.find('[data-testid="skill-name-input"]').setValue('edited-name')
    expect(wrapper.find('[data-testid="skill-download-button"]').attributes('disabled')).toBeDefined()
  })

  it('uploads a supporting file into the package payload', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-name-input"]').setValue('backend-review')
    await wrapper.find('[data-testid="skill-markdown-input"]').setValue('---\nname: backend-review\ndescription: Review backend changes.\n---\n\nInspect API and database behavior.\n')

    const input = wrapper.find('input[type="file"]')
    const file = new File(['# Guide\n'], 'guide.md', { type: 'text/markdown' })
    Object.defineProperty(input.element, 'files', { value: [file], configurable: true })
    await input.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('.skill-settings__file').exists()).toBe(true)
    })

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
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
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()
    await wrapper.find('[data-testid="skill-markdown-input"]').setValue(
      `${skill.skill_md}\nReview the final payload.\n`,
    )

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
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

  it('sends only enabled when package content is unchanged', async () => {
    api.updateSkill.mockResolvedValue({ ...skill, enabled: false })
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    await wrapper.findAll('.switch')[0].trigger('click')
    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()

    expect(api.updateSkill).toHaveBeenCalledWith(4, { enabled: false })
  })

  it('keeps the same path input mounted while its value is edited', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    const pathInput = wrapper.find('.skill-settings__file input')
    const originalElement = pathInput.element
    await pathInput.setValue('scripts/review.sh')

    expect(wrapper.find('.skill-settings__file input').element).toBe(originalElement)
  })

  it('preserves executable permission when replacing an existing file', async () => {
    const executableSkill = {
      ...skill,
      files: [{
        path: 'bin/tool',
        content_base64: 'b2xkIHRvb2w=',
        executable: true,
      }],
    }
    api.getAdminSkills.mockResolvedValue([executableSkill])
    api.getAdminSkill.mockResolvedValue(executableSkill)
    api.updateSkill.mockResolvedValue(executableSkill)
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    const replacement = new File(['new tool'], 'tool')
    Object.defineProperty(replacement, 'webkitRelativePath', {
      value: 'bin/tool',
      configurable: true,
    })
    const folderInput = wrapper.findAll('input[type="file"]')[1]
    Object.defineProperty(folderInput.element, 'files', {
      value: [replacement],
      configurable: true,
    })
    await folderInput.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="skill-save-button"]').attributes('disabled')).toBeUndefined()
    })

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()

    expect(api.updateSkill).toHaveBeenCalledWith(4, expect.objectContaining({
      files: [{
        path: 'bin/tool',
        content_base64: 'bmV3IHRvb2w=',
        executable: true,
      }],
    }))
  })

  it('preserves executable permission when reimporting a complete package', async () => {
    const executableSkill = {
      ...skill,
      files: [{
        path: 'bin/tool',
        content_base64: 'b2xkIHRvb2w=',
        executable: true,
      }],
    }
    api.getAdminSkills.mockResolvedValue([executableSkill])
    api.getAdminSkill.mockResolvedValue(executableSkill)
    api.updateSkill.mockResolvedValue(executableSkill)
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    const skillMd = new File([skill.skill_md], 'SKILL.md', { type: 'text/markdown' })
    const replacement = new File(['new tool'], 'tool')
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'review-changes/SKILL.md',
      configurable: true,
    })
    Object.defineProperty(replacement, 'webkitRelativePath', {
      value: 'review-changes/bin/tool',
      configurable: true,
    })
    const folderInput = wrapper.findAll('input[type="file"]')[1]
    Object.defineProperty(folderInput.element, 'files', {
      value: [skillMd, replacement],
      configurable: true,
    })
    await folderInput.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="skill-save-button"]').attributes('disabled')).toBeUndefined()
    })

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()

    expect(api.updateSkill).toHaveBeenCalledWith(4, expect.objectContaining({
      files: [{
        path: 'bin/tool',
        content_base64: 'bmV3IHRvb2w=',
        executable: true,
      }],
    }))
  })

  it('locks skill switching and route navigation while a save is in flight', async () => {
    let resolveUpdate!: (value: typeof skill) => void
    api.updateSkill.mockImplementation(() => new Promise((resolve) => {
      resolveUpdate = resolve
    }))
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()
    const updatedMarkdown = `${skill.skill_md}\nReview the final payload.\n`
    await wrapper.find('[data-testid="skill-markdown-input"]').setValue(updatedMarkdown)

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await wrapper.vm.$nextTick()

    expect((wrapper.find('[data-testid="skill-create-button"]').element as HTMLButtonElement).disabled)
      .toBe(true)
    expect((wrapper.find('[data-testid="skill-list-item-4"]').element as HTMLButtonElement).disabled)
      .toBe(true)
    expect(routeState.leaveGuard?.()).toBe(false)

    resolveUpdate({ ...skill, skill_md: updatedMarkdown })
    await flushPromises()
    expect((wrapper.find('[data-testid="skill-create-button"]').element as HTMLButtonElement).disabled)
      .toBe(false)
  })

  it('imports a complete folder without dropping SKILL.md metadata', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const inputs = wrapper.findAll('input[type="file"]')
    const skillMd = new File([
      '---\nname: imported-skill\ndescription: Imported package.\nallowed-tools: Read Grep\ncontext: fork\n---\n\nRun the imported workflow.\n',
    ], 'SKILL.md', { type: 'text/markdown' })
    const guide = new File(['# API guide\n'], 'guide.md', { type: 'text/markdown' })
    const script = new File(['#!/bin/sh\n'], 'check.sh', { type: 'text/x-shellscript' })
    const binary = new File(['binary'], 'tool', { type: 'application/octet-stream' })
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'package-folder/SKILL.md',
      configurable: true,
    })
    Object.defineProperty(guide, 'webkitRelativePath', {
      value: 'package-folder/references/platform/api/v2/guide.md',
      configurable: true,
    })
    Object.defineProperty(script, 'webkitRelativePath', {
      value: 'package-folder/scripts/tools/check.sh',
      configurable: true,
    })
    Object.defineProperty(binary, 'webkitRelativePath', {
      value: 'package-folder/bin/tool',
      configurable: true,
    })
    Object.defineProperty(inputs[1].element, 'files', {
      value: [skillMd, guide, script, binary],
      configurable: true,
    })
    await inputs[1].trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('.skill-settings__file').exists()).toBe(true)
    })

    expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('imported-skill')
    expect(wrapper.find('[data-testid="skill-markdown-input"]').element.value).toContain('allowed-tools: Read Grep')
    expect(wrapper.find('[data-testid="skill-markdown-input"]').element.value).toContain('context: fork')

    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()
    expect(api.createSkill).toHaveBeenCalledWith(expect.objectContaining({
      name: 'imported-skill',
      skill_md: expect.stringContaining('allowed-tools: Read Grep'),
      files: [
        expect.objectContaining({ path: 'bin/tool', executable: true }),
        expect.objectContaining({ path: 'references/platform/api/v2/guide.md', executable: false }),
        expect.objectContaining({ path: 'scripts/tools/check.sh', executable: true }),
      ],
    }))
  })

  it('extracts a Skill name followed by a valid YAML inline comment', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const skillMd = new File([
      '---\nname: "imported-\\u0073kill" # stable identifier\ndescription: Imported package.\n---\n\nRun the imported workflow.\n',
    ], 'SKILL.md', { type: 'text/markdown' })
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'imported-skill/SKILL.md',
      configurable: true,
    })
    const folderInput = wrapper.findAll('input[type="file"]')[1]
    Object.defineProperty(folderInput.element, 'files', {
      value: [skillMd],
      configurable: true,
    })

    await folderInput.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('imported-skill')
    })
  })

  it('uses the backend YAML 1.1 semantics when extracting a Skill name', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const skillMd = new File([
      '---\nname: on\ndescription: YAML 1.1 treats this name as a boolean.\n---\n\nRun the workflow.\n',
    ], 'SKILL.md', { type: 'text/markdown' })
    Object.defineProperty(skillMd, 'webkitRelativePath', {
      value: 'boolean-name/SKILL.md',
      configurable: true,
    })
    const folderInput = wrapper.findAll('input[type="file"]')[1]
    Object.defineProperty(folderInput.element, 'files', {
      value: [skillMd],
      configurable: true,
    })

    await folderInput.trigger('change')
    await flushPromises()

    expect(wrapper.find('[data-testid="skill-name-input"]').element.value).toBe('')
  })

  it('adds a deeply nested dependency directory relative to the Skill root', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()

    const inputs = wrapper.findAll('input[type="file"]')
    const guide = new File(['# API guide\n'], 'guide.md', { type: 'text/markdown' })
    const example = new File(['{}\n'], 'request.json', { type: 'application/json' })
    Object.defineProperty(guide, 'webkitRelativePath', {
      value: 'references/platform/api/v2/guide.md',
      configurable: true,
    })
    Object.defineProperty(example, 'webkitRelativePath', {
      value: 'references/platform/examples/request.json',
      configurable: true,
    })
    Object.defineProperty(inputs[1].element, 'files', {
      value: [guide, example],
      configurable: true,
    })

    await inputs[1].trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.findAll('.skill-settings__file')).toHaveLength(3)
    })
    await wrapper.find('[data-testid="skill-save-button"]').trigger('click')
    await flushPromises()

    expect(api.updateSkill).toHaveBeenCalledWith(4, expect.objectContaining({
      files: [
        expect.objectContaining({ path: 'references/platform/api/v2/guide.md' }),
        expect.objectContaining({ path: 'references/platform/examples/request.json' }),
        expect.objectContaining({ path: 'scripts/check.sh' }),
      ],
    }))
  })

  it('blocks file and directory path conflicts before saving', async () => {
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    await wrapper.find('[data-testid="skill-list-item-4"]').trigger('click')
    await flushPromises()
    await wrapper.find('.skill-settings__file input').setValue('scripts')

    const input = wrapper.findAll('input[type="file"]')[0]
    const nestedScript = new File(['#!/bin/sh\n'], 'check.sh', {
      type: 'text/x-shellscript',
    })
    Object.defineProperty(nestedScript, 'webkitRelativePath', {
      value: 'scripts/tools/check.sh',
      configurable: true,
    })
    Object.defineProperty(input.element, 'files', {
      value: [nestedScript],
      configurable: true,
    })
    await input.trigger('change')
    await vi.waitFor(() => {
      expect(wrapper.findAll('.skill-settings__file-path-error')).toHaveLength(2)
    })

    expect(wrapper.find('[data-testid="skill-save-button"]').attributes('disabled')).toBeDefined()
    expect(api.updateSkill).not.toHaveBeenCalled()
  })

  it('keeps the existing draft unchanged when a folder import fails', async () => {
    api.getAdminSkills.mockResolvedValue([])
    const wrapper = mount(SkillSettingsPanel)
    await flushPromises()
    const nameInput = wrapper.find('[data-testid="skill-name-input"]')
    const markdownInput = wrapper.find('[data-testid="skill-markdown-input"]')
    await nameInput.setValue('existing-skill')
    await markdownInput.setValue(
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

    expect(nameInput.element.value).toBe('existing-skill')
    expect(markdownInput.element.value).toContain('Keep this draft.')
    expect(wrapper.find('.skill-settings__file').exists()).toBe(false)
  })
})
