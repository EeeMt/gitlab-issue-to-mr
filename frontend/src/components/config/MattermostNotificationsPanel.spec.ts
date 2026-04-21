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
  const mock = {
    getMattermostNotificationConfig: vi.fn<() => Promise<any>>(() => Promise.resolve({ integration: {}, profiles: [] })),
    createMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    updateMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve()),
    deleteMattermostNotificationProfile: vi.fn<() => Promise<any>>(() => Promise.resolve())
  }
  const resetMockApi = () => {
    Object.values(mock).forEach(fn => {
      if (typeof fn.mock !== 'undefined') fn.mockReset()
    })
  }
  return { mockApi: mock, resetMockApi }
})

vi.mock('../../api', () => ({
  getMattermostNotificationConfig: mockApi.getMattermostNotificationConfig,
  createMattermostNotificationProfile: mockApi.createMattermostNotificationProfile,
  updateMattermostNotificationProfile: mockApi.updateMattermostNotificationProfile,
  deleteMattermostNotificationProfile: mockApi.deleteMattermostNotificationProfile
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
      team_name: 'team-x',
      channel_name: 'ch',
      mention_in_channel: false,
      send_for_manual_tasks: false,
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
      team_name: 'team',
      channel_name: 'chan',
      mention_in_channel: false,
      send_for_manual_tasks: true,
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
})
