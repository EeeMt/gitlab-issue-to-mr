import { mount } from '@vue/test-utils'
import { vi, describe, it, expect, beforeEach } from 'vitest'

// Mock i18n
vi.mock('vue-i18n', () => ({
  useI18n: () => ({ t: (k: string) => k })
}))

// Mock naive-ui's useMessage but keep actual components so stubs in mount work
vi.mock('naive-ui', async () => {
  const actual = await vi.importActual<any>('naive-ui')
  return {
    ...actual,
    useMessage: () => ({ success: () => {}, error: () => {} })
  }
})

import MattermostNotificationsPanel from './MattermostNotificationsPanel.vue'

// Hoisted mock API so vi.mock can reference the functions safely
const { mockApi, resetMockApi } = vi.hoisted(() => {
  const defaultChannelTarget = () => ({
    channel_id: 'channel-42',
    team_name: 'engineering',
    team_display_name: 'Engineering',
    channel_name: 'codify-alerts',
    channel_display_name: 'Codify Alerts'
  })

  const mock = {
    getMattermostNotificationConfig: vi.fn<() => Promise<any>>(() => Promise.resolve({ integration: {}, profiles: [] })),
    createMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    updateMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    deleteMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    resolveMattermostChannelTarget: vi.fn<() => Promise<any>>(() => Promise.resolve(defaultChannelTarget())),
    getMattermostChannelTarget: vi.fn<() => Promise<any>>(() => Promise.resolve(defaultChannelTarget()))
  }
  const resetMockApi = () => {
    mock.getMattermostNotificationConfig.mockReset()
    mock.getMattermostNotificationConfig.mockImplementation(() => Promise.resolve({ integration: {}, profiles: [] }))
    mock.createMattermostNotificationProfile.mockReset()
    mock.createMattermostNotificationProfile.mockImplementation(() => Promise.resolve())
    mock.updateMattermostNotificationProfile.mockReset()
    mock.updateMattermostNotificationProfile.mockImplementation(() => Promise.resolve())
    mock.deleteMattermostNotificationProfile.mockReset()
    mock.deleteMattermostNotificationProfile.mockImplementation(() => Promise.resolve())
    mock.resolveMattermostChannelTarget.mockReset()
    mock.resolveMattermostChannelTarget.mockImplementation(() => Promise.resolve(defaultChannelTarget()))
    mock.getMattermostChannelTarget.mockReset()
    mock.getMattermostChannelTarget.mockImplementation(() => Promise.resolve(defaultChannelTarget()))
  }
  return { mockApi: mock, resetMockApi }
})

vi.mock('../../api', () => ({
  getMattermostNotificationConfig: mockApi.getMattermostNotificationConfig,
  createMattermostNotificationProfile: mockApi.createMattermostNotificationProfile,
  updateMattermostNotificationProfile: mockApi.updateMattermostNotificationProfile,
  deleteMattermostNotificationProfile: mockApi.deleteMattermostNotificationProfile,
  resolveMattermostChannelTarget: mockApi.resolveMattermostChannelTarget,
  getMattermostChannelTarget: mockApi.getMattermostChannelTarget
}))

describe('MattermostNotificationsPanel', () => {
  beforeEach(() => {
    resetMockApi()
  })

  it('opens create modal with default profile form', async () => {
    const wrapper = mount(MattermostNotificationsPanel, {
      props: { isMobile: false, reloadKey: 0 },
      global: {
        stubs: ['NCard', 'NButton', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NSelect', 'NSpace', 'NGrid', 'NGi', 'NCheckbox', 'NCheckboxGroup', 'NSwitch', 'NTag']
      }
    })

    // Open create modal
    // @ts-ignore
    await wrapper.vm.openCreateProfileModal()

    // @ts-ignore
    expect(wrapper.vm.profileModalVisible).toBe(true)
    // @ts-ignore
    expect(wrapper.vm.editingProfileId).toBe(null)
    // form defaults
    // @ts-ignore
    expect(wrapper.vm.profileForm.name).toBe('')
    // @ts-ignore
    expect(wrapper.vm.profileForm.enabled).toBe(true)
    // @ts-ignore
    expect(wrapper.vm.profileForm.target_type).toBe('channel')
  })

  it('opens edit modal with populated form', async () => {
    const profile = {
      id: 5,
      name: 'Alert Profile',
      enabled: false,
      target_type: 'initiator_dm',
      channel_id: null,
      mention_in_channel: false,
      event_types: ['task_failed'],
      field_keys: ['task_id']
    }

    const wrapper = mount(MattermostNotificationsPanel, {
      props: { isMobile: false, reloadKey: 0 },
      global: {
        stubs: ['NCard', 'NButton', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NSelect', 'NSpace', 'NGrid', 'NGi', 'NCheckbox', 'NCheckboxGroup', 'NSwitch', 'NTag']
      }
    })

    // @ts-ignore
    await wrapper.vm.openEditProfileModal(profile)

    // @ts-ignore
    expect(wrapper.vm.profileModalVisible).toBe(true)
    // @ts-ignore
    expect(wrapper.vm.editingProfileId).toBe(5)
    // @ts-ignore
    expect(wrapper.vm.profileForm.name).toBe('Alert Profile')
    // @ts-ignore
    expect(wrapper.vm.profileForm.target_type).toBe('initiator_dm')
  })

  it('closing/resetting the modal clears edit and form state (cancel & save)', async () => {
    const profile = {
      id: 7,
      name: 'To Edit',
      enabled: true,
      target_type: 'channel',
      channel_id: 'channel-42',
      mention_in_channel: false,
      event_types: ['task_completed'],
      field_keys: ['task_id']
    }

    const wrapper = mount(MattermostNotificationsPanel, {
      props: { isMobile: false, reloadKey: 0 },
      global: {
        stubs: ['NCard', 'NButton', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NSelect', 'NSpace', 'NGrid', 'NGi', 'NCheckbox', 'NCheckboxGroup', 'NSwitch', 'NTag']
      }
    })

    // Open edit
    // @ts-ignore
    await wrapper.vm.openEditProfileModal(profile)
    // ensure edit state
    // @ts-ignore
    expect(wrapper.vm.editingProfileId).toBe(7)

    // Simulate cancel via closeProfileModal
    // @ts-ignore
    wrapper.vm.closeProfileModal()

    // @ts-ignore
    expect(wrapper.vm.editingProfileId).toBe(null)
    // @ts-ignore
    expect(wrapper.vm.profileForm.name).toBe('')

    // Now test save path resets state
    // Open edit again
    // @ts-ignore
    await wrapper.vm.openEditProfileModal(profile)
    // provide formRef validate
    // @ts-ignore
    wrapper.vm.profileFormRef = { validate: () => Promise.resolve() }

    // Mock update API
    mockApi.updateMattermostNotificationProfile.mockResolvedValue({})

    // @ts-ignore
    await wrapper.vm.handleSaveProfile()

    // after save, editingProfileId should be cleared and form reset
    // @ts-ignore
    expect(wrapper.vm.editingProfileId).toBe(null)
    // @ts-ignore
    expect(wrapper.vm.profileForm.name).toBe('')
  })

  it('builds payload without deprecated manual-task flag', async () => {
    const wrapper = mount(MattermostNotificationsPanel, {
      props: { isMobile: false, reloadKey: 0 },
      global: {
        stubs: ['NCard', 'NButton', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NSelect', 'NSpace', 'NGrid', 'NGi', 'NCheckbox', 'NCheckboxGroup', 'NSwitch', 'NTag']
      }
    })

    // @ts-ignore
    await wrapper.vm.openCreateProfileModal()
    // @ts-ignore
    wrapper.vm.profileForm.name = 'Channel Alerts'
    // @ts-ignore
    wrapper.vm.channelLookupForm.team_name = 'engineering'
    // @ts-ignore
    wrapper.vm.channelLookupForm.channel_name = 'codify-alerts'
    // @ts-ignore
    wrapper.vm.profileForm.channel_id = 'channel-42'

    // @ts-ignore
    const payload = wrapper.vm.buildProfilePayload()

    expect(payload).toMatchObject({
      name: 'Channel Alerts',
      target_type: 'channel',
      channel_id: 'channel-42'
    })
    expect('send_for_manual_tasks' in payload).toBe(false)
    expect('team_name' in payload).toBe(false)
    expect('channel_name' in payload).toBe(false)
  })

  it('resolves channel target explicitly before save', async () => {
    const wrapper = mount(MattermostNotificationsPanel, {
      props: { isMobile: false, reloadKey: 0 },
      global: {
        stubs: ['NCard', 'NButton', 'NModal', 'NForm', 'NFormItem', 'NInput', 'NSelect', 'NSpace', 'NGrid', 'NGi', 'NCheckbox', 'NCheckboxGroup', 'NSwitch', 'NTag']
      }
    })

    // @ts-ignore
    await wrapper.vm.openCreateProfileModal()
    // @ts-ignore
    wrapper.vm.channelLookupForm.team_name = 'engineering'
    // @ts-ignore
    wrapper.vm.channelLookupForm.channel_name = 'codify-alerts'

    // @ts-ignore
    await wrapper.vm.handleResolveChannelTarget()

    expect(mockApi.resolveMattermostChannelTarget).toHaveBeenCalledWith({
      team_name: 'engineering',
      channel_name: 'codify-alerts'
    })
    // @ts-ignore
    expect(wrapper.vm.profileForm.channel_id).toBe('channel-42')
    // @ts-ignore
    expect(wrapper.vm.resolvedChannelTarget.channel_display_name).toBe('Codify Alerts')
  })
})
