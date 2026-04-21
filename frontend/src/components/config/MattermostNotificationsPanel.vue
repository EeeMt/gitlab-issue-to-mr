<template>
  <n-spin :show="loading">
    <div class="config-layout__main">
      <n-card class="config-form-card" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">{{ t('config.mattermostIntegration') }}</div>
              <div class="config-card-header__subtitle">{{ t('config.mattermostIntegrationSubtitle') }}</div>
            </div>
          </div>
        </template>

        <n-form
          ref="integrationFormRef"
          :model="integrationForm"
          :rules="integrationRules"
          label-placement="top"
          class="config-section-form"
        >
          <div class="config-form__section">
            <div class="config-form__section-title">{{ t('config.mattermostConnection') }}</div>
            <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
              <n-gi>
                <n-form-item :label="t('config.mattermostServerUrl')" path="mattermost_server_url">
                  <n-input
                    v-model:value="integrationForm.mattermost_server_url"
                    placeholder="https://mattermost.example.com"
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.mattermostServerUrlHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi>
                <n-form-item :label="t('config.mattermostBotTokenStatus')">
                  <n-tag :type="integrationForm.mattermost_bot_token_configured ? 'success' : 'warning'" round>
                    {{ integrationForm.mattermost_bot_token_configured ? t('config.configured') : t('config.missing') }}
                  </n-tag>
                  <template #feedback>
                    {{ t('config.mattermostBotTokenStatusHint') }}
                  </template>
                </n-form-item>
              </n-gi>
              <n-gi :span="isMobile ? 1 : 2">
                <n-form-item :label="t('config.mattermostBotToken')">
                  <n-input
                    v-model:value="integrationForm.mattermost_bot_token_input"
                    type="password"
                    show-password-on="click"
                    :placeholder="
                      integrationForm.mattermost_bot_token_configured
                        ? t('config.configuredEnterNew')
                        : t('config.enterMattermostBotToken')
                    "
                    class="config-form__input"
                  />
                  <template #feedback>
                    {{ t('config.mattermostBotTokenHint') }}
                  </template>
                </n-form-item>
              </n-gi>
            </n-grid>
          </div>

          <div class="config-card-actions">
            <n-space :size="12" wrap>
              <n-button
                type="primary"
                :loading="integrationSaving"
                :disabled="isBusy || !isIntegrationDirty"
                @click="handleSaveIntegration"
              >
                {{ t('config.saveChanges') }}
              </n-button>
              <n-button secondary :disabled="isBusy || !isIntegrationDirty" @click="resetIntegration">
                {{ t('config.revertChanges') }}
              </n-button>
              <n-button :loading="mattermostTesting" :disabled="isBusy" @click="handleTestIntegration">
                {{ t('config.testMattermostConnection') }}
              </n-button>
              <n-button
                :disabled="isBusy || !integrationForm.mattermost_bot_token_configured"
                @click="handleClearBotToken"
              >
                {{ t('config.clearMattermostBotToken') }}
              </n-button>
            </n-space>
            <n-alert
              v-if="integrationTestState"
              :type="integrationTestState.type"
              :show-icon="false"
              class="config-actions__alert"
            >
              {{ integrationTestState.message }}
            </n-alert>
          </div>
        </n-form>
      </n-card>

      <n-card class="config-form-card" :bordered="false">
        <template #header>
          <div class="config-card-header">
            <div>
              <div class="config-card-header__title">{{ t('config.notificationProfiles') }}</div>
              <div class="config-card-header__subtitle">{{ t('config.notificationProfilesSubtitle') }}</div>
            </div>
            <n-button type="primary" secondary @click="openCreateProfileModal">
              {{ t('config.addNotificationProfile') }}
            </n-button>
          </div>
        </template>

        <div v-if="profiles.length === 0" class="config-notification-empty">
          {{ t('config.noNotificationProfiles') }}
        </div>

        <div v-else class="config-notification-list">
          <div
            v-for="profile in profiles"
            :key="profile.id"
            class="config-notification-profile"
          >
            <div class="config-notification-profile__top">
              <div>
                <div class="config-notification-profile__title">{{ profile.name }}</div>
                <div class="config-notification-profile__meta">
                  {{ getTargetSummary(profile) }}
                </div>
              </div>
              <n-space :size="8" wrap>
                <n-tag :type="profile.enabled ? 'success' : 'default'" round>
                  {{ profile.enabled ? t('common.enabled') : t('common.disabled') }}
                </n-tag>
                <n-tag round>{{ getTargetLabel(profile.target_type) }}</n-tag>
                <n-tag
                  v-if="profile.target_type === 'channel' && profile.mention_in_channel"
                  type="info"
                  round
                >
                  {{ t('config.mentionInitiatorInChannel') }}
                </n-tag>
              </n-space>
            </div>

            <div class="config-notification-profile__section">
              <div class="config-notification-profile__label">{{ t('config.notificationEvents') }}</div>
              <n-space :size="6" wrap>
                <n-tag v-for="eventType in profile.event_types" :key="eventType" size="small" round>
                  {{ getEventLabel(eventType) }}
                </n-tag>
              </n-space>
            </div>

            <div class="config-notification-profile__section">
              <div class="config-notification-profile__label">{{ t('config.notificationFields') }}</div>
              <n-space :size="6" wrap>
                <n-tag v-for="fieldKey in profile.field_keys" :key="fieldKey" size="small" round>
                  {{ getFieldLabel(fieldKey) }}
                </n-tag>
              </n-space>
            </div>

            <div class="config-notification-profile__footer">
              <n-space :size="8" wrap>
                <n-button size="small" secondary @click="openEditProfileModal(profile)">
                  {{ t('config.editNotificationProfile') }}
                </n-button>
                <n-button
                  size="small"
                  :loading="deletingProfileId === profile.id"
                  :disabled="isBusy && deletingProfileId !== profile.id"
                  @click="handleDeleteProfile(profile)"
                >
                  {{ t('config.deleteNotificationProfile') }}
                </n-button>
              </n-space>
            </div>
          </div>
        </div>
      </n-card>
    </div>
  </n-spin>

  <n-modal
    class="config-editor-modal"
    v-model:show="profileModalVisible"
    preset="card"
    :style="{ width: isMobile ? '96vw' : '760px' }"
  >
    <template #header>
      <div class="config-editor-modal__header">
        <div class="config-card-header__title">
          {{ editingProfileId === null ? t('config.createNotificationProfile') : t('config.editNotificationProfile') }}
        </div>
        <div class="config-card-header__subtitle">
          {{ t('config.notificationProfileModalSubtitle') }}
        </div>
      </div>
    </template>

    <div class="config-editor-modal__scroll">
      <n-form
        ref="profileFormRef"
        :model="profileForm"
        :rules="profileRules"
        label-placement="top"
        class="config-section-form config-section-form--compact"
      >
        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.notificationProfileBasics') }}</div>
          <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
            <n-gi>
              <n-form-item :label="t('config.profileName')" path="name">
                <n-input v-model:value="profileForm.name" :placeholder="t('config.enterProfileName')" />
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.notificationTarget')" path="target_type">
                <n-select
                  v-model:value="profileForm.target_type"
                  :options="targetOptions"
                />
                <template #feedback>
                  {{
                    profileForm.target_type === 'channel'
                      ? t('config.notificationTargetChannelHint')
                      : t('config.notificationTargetInitiatorDmHint')
                    }}
                </template>
              </n-form-item>
            </n-gi>
          </n-grid>
          <div class="config-inline-toggle">
            <span class="config-inline-toggle__label">{{ t('config.profileEnabled') }}</span>
            <n-switch v-model:value="profileForm.enabled" />
          </div>
        </div>

        <div v-if="profileForm.target_type === 'channel'" class="config-form__section">
          <div class="config-form__section-title">{{ t('config.notificationChannelTarget') }}</div>
          <n-grid
            :cols="isMobile ? 1 : 2"
            :x-gap="16"
            :y-gap="8"
            class="config-channel-target__grid"
          >
            <n-gi>
              <n-form-item :label="t('config.mattermostTeamName')">
                <n-input
                  v-model:value="channelLookupForm.team_name"
                  :placeholder="t('config.enterMattermostTeamName')"
                />
              </n-form-item>
            </n-gi>
            <n-gi>
              <n-form-item :label="t('config.mattermostChannelName')">
                <n-input
                  v-model:value="channelLookupForm.channel_name"
                  :placeholder="t('config.enterMattermostChannelName')"
                />
              </n-form-item>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <n-form-item path="channel_id" :show-label="false" class="config-channel-target__resolve-item">
                <div class="config-channel-target__actions">
                  <div class="config-channel-target__hint">
                    {{
                      editingProfileId === null
                        ? t('config.resolveMattermostChannelTargetHint')
                        : t('config.resolveMattermostChannelTargetEditHint')
                    }}
                  </div>
                  <n-button
                    secondary
                    :loading="resolvingChannelTarget || loadingChannelTarget"
                    :disabled="profileSaving"
                    @click="handleResolveChannelTarget"
                  >
                    {{ t('config.resolveMattermostChannelTarget') }}
                  </n-button>
                </div>
              </n-form-item>
            </n-gi>
            <n-gi v-if="resolvedChannelTarget" :span="isMobile ? 1 : 2">
              <n-alert
                type="success"
                :show-icon="false"
                class="config-channel-target__alert"
              >
                {{
                  t('config.resolvedMattermostChannelTarget', {
                    team: resolvedChannelTarget.team_display_name,
                    channel: resolvedChannelTarget.channel_display_name,
                    channelId: resolvedChannelTarget.channel_id
                  })
                }}
              </n-alert>
            </n-gi>
            <n-gi :span="isMobile ? 1 : 2">
              <div class="config-inline-toggle">
                <div class="config-inline-toggle__content">
                  <div class="config-inline-toggle__label">
                    {{ t('config.mentionInitiatorInChannel') }}
                  </div>
                  <div class="config-inline-toggle__hint">
                    {{ t('config.mentionInitiatorInChannelHint') }}
                  </div>
                </div>
                <n-switch v-model:value="profileForm.mention_in_channel" />
              </div>
            </n-gi>
          </n-grid>
        </div>

        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.notificationEvents') }}</div>
          <n-form-item path="event_types">
            <n-checkbox-group v-model:value="profileForm.event_types">
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi v-for="option in eventOptions" :key="option.value">
                  <n-checkbox :value="option.value" :label="option.label" />
                </n-gi>
              </n-grid>
            </n-checkbox-group>
          </n-form-item>
        </div>

        <div class="config-form__section">
          <div class="config-form__section-title">{{ t('config.notificationFields') }}</div>
          <n-form-item path="field_keys">
            <n-checkbox-group v-model:value="profileForm.field_keys">
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi v-for="option in fieldOptions" :key="option.value">
                  <n-checkbox :value="option.value" :label="option.label" />
                </n-gi>
              </n-grid>
            </n-checkbox-group>
          </n-form-item>
        </div>
      </n-form>
    </div>

    <template #footer>
      <n-space justify="end" :size="12">
        <n-button secondary :disabled="profileSaving" @click="closeProfileModal">
          {{ t('common.cancel') }}
        </n-button>
        <n-button type="primary" :loading="profileSaving" @click="handleSaveProfile">
          {{ t('config.saveChanges') }}
        </n-button>
      </n-space>
    </template>
  </n-modal>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import {
  NAlert,
  NButton,
  NCard,
  NCheckbox,
  NCheckboxGroup,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  useMessage,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  createMattermostNotificationProfile,
  deleteMattermostNotificationProfile,
  getMattermostChannelTarget,
  getMattermostNotificationConfig,
  resolveMattermostChannelTarget,
  testMattermostIntegration,
  updateMattermostIntegration,
  updateMattermostNotificationProfile,
  type MattermostChannelTarget,
  type MattermostIntegrationUpdate,
  type MattermostNotificationEventType,
  type MattermostNotificationFieldKey,
  type MattermostNotificationProfile,
  type MattermostNotificationProfilePayload,
  type MattermostNotificationTargetType
} from '../../api'

type IntegrationForm = {
  mattermost_server_url: string
  mattermost_bot_token_configured: boolean
  mattermost_bot_token_input: string
}

type ProfileForm = {
  name: string
  enabled: boolean
  target_type: MattermostNotificationTargetType
  channel_id: string
  mention_in_channel: boolean
  event_types: MattermostNotificationEventType[]
  field_keys: MattermostNotificationFieldKey[]
}

type ChannelLookupForm = {
  team_name: string
  channel_name: string
}

type TestState = {
  type: 'success' | 'error'
  message: string
}

const props = defineProps<{
  isMobile: boolean
  reloadKey: number
}>()

const message = useMessage()
const { t } = useI18n()

const loading = ref(false)
const integrationSaving = ref(false)
const mattermostTesting = ref(false)
const profileSaving = ref(false)
const deletingProfileId = ref<number | null>(null)
const profileModalVisible = ref(false)
const editingProfileId = ref<number | null>(null)
const integrationTestState = ref<TestState | null>(null)
const resolvingChannelTarget = ref(false)
const loadingChannelTarget = ref(false)
const resolvedChannelTarget = ref<MattermostChannelTarget | null>(null)
const integrationFormRef = ref<FormInst | null>(null)
const profileFormRef = ref<FormInst | null>(null)
const suppressChannelLookupReset = ref(false)

const integrationForm = ref<IntegrationForm>({
  mattermost_server_url: '',
  mattermost_bot_token_configured: false,
  mattermost_bot_token_input: ''
})
const lastLoadedIntegration = ref<IntegrationForm>({ ...integrationForm.value })
const profiles = ref<MattermostNotificationProfile[]>([])

function createEmptyProfileForm(): ProfileForm {
  return {
    name: '',
    enabled: true,
    target_type: 'channel',
    channel_id: '',
    mention_in_channel: true,
    event_types: ['task_completed', 'task_failed'],
    field_keys: ['task_id', 'project', 'status', 'task_link']
  }
}

const profileForm = reactive<ProfileForm>(createEmptyProfileForm())
const channelLookupForm = reactive<ChannelLookupForm>({
  team_name: '',
  channel_name: ''
})

const isBusy = computed(
  () => loading.value || integrationSaving.value || mattermostTesting.value || profileSaving.value
)

const isMobile = computed(() => props.isMobile)

const eventOptions = computed(() => [
  { label: t('config.notificationEventTaskCompleted'), value: 'task_completed' as MattermostNotificationEventType },
  { label: t('config.notificationEventTaskFailed'), value: 'task_failed' as MattermostNotificationEventType },
  { label: t('config.notificationEventTaskRescheduled'), value: 'task_rescheduled' as MattermostNotificationEventType },
  { label: t('config.notificationEventTaskExecuteNow'), value: 'task_execute_now' as MattermostNotificationEventType },
  { label: t('config.notificationEventTaskRetryScheduled'), value: 'task_retry_scheduled' as MattermostNotificationEventType },
  { label: t('config.notificationEventTaskCancelled'), value: 'task_cancelled' as MattermostNotificationEventType }
])

const fieldOptions = computed(() => [
  { label: t('config.notificationFieldTaskId'), value: 'task_id' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldProject'), value: 'project' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldIssue'), value: 'issue' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldMergeRequest'), value: 'merge_request' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldInitiator'), value: 'initiator' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldStatus'), value: 'status' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldBranch'), value: 'branch' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldTargetBranch'), value: 'target_branch' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldScheduledAt'), value: 'scheduled_at' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldScheduleChange'), value: 'schedule_change' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldError'), value: 'error' as MattermostNotificationFieldKey },
  { label: t('config.notificationFieldTaskLink'), value: 'task_link' as MattermostNotificationFieldKey }
])

const targetOptions = computed(() => [
  { label: t('config.notificationTargetChannel'), value: 'channel' as MattermostNotificationTargetType },
  { label: t('config.notificationTargetInitiatorDm'), value: 'initiator_dm' as MattermostNotificationTargetType }
])

const integrationRules: FormRules = {
  mattermost_server_url: {
    validator: () =>
      !!integrationForm.value.mattermost_server_url.trim() || new Error(t('config.enterMattermostServerUrl')),
    trigger: ['blur', 'input']
  }
}

const profileRules: FormRules = {
  name: {
    validator: () => !!profileForm.name.trim() || new Error(t('config.enterProfileName')),
    trigger: ['blur', 'input']
  },
  target_type: {
    required: true,
    message: t('config.selectNotificationTarget'),
    trigger: 'change'
  },
  channel_id: {
    validator: () =>
      profileForm.target_type !== 'channel' ||
      !!profileForm.channel_id.trim() ||
      new Error(t('config.resolveMattermostChannelTargetFirst')),
    trigger: ['blur', 'change']
  },
  event_types: {
    validator: () => profileForm.event_types.length > 0 || new Error(t('config.selectNotificationEvents')),
    trigger: 'change'
  },
  field_keys: {
    validator: () => profileForm.field_keys.length > 0 || new Error(t('config.selectNotificationFields')),
    trigger: 'change'
  }
}

const isIntegrationDirty = computed(
  () =>
    JSON.stringify({
      mattermost_server_url: integrationForm.value.mattermost_server_url,
      mattermost_bot_token_input: integrationForm.value.mattermost_bot_token_input
    }) !==
    JSON.stringify({
      mattermost_server_url: lastLoadedIntegration.value.mattermost_server_url,
      mattermost_bot_token_input: lastLoadedIntegration.value.mattermost_bot_token_input
    })
)

function syncFromServer(config: Awaited<ReturnType<typeof getMattermostNotificationConfig>>) {
  integrationForm.value = {
    mattermost_server_url: config.integration.mattermost_server_url,
    mattermost_bot_token_configured: config.integration.mattermost_bot_token_configured,
    mattermost_bot_token_input: ''
  }
  lastLoadedIntegration.value = { ...integrationForm.value }
  profiles.value = config.profiles
}

async function fetchNotifications(showError = true) {
  loading.value = true
  try {
    syncFromServer(await getMattermostNotificationConfig())
  } catch {
    if (showError) {
      message.error(t('config.failedToFetchNotifications'))
    }
  } finally {
    loading.value = false
  }
}

function resetIntegration() {
  integrationForm.value = { ...lastLoadedIntegration.value }
  integrationTestState.value = null
}

function buildIntegrationPayload(): MattermostIntegrationUpdate {
  const payload: MattermostIntegrationUpdate = {
    mattermost_server_url: integrationForm.value.mattermost_server_url.trim()
  }
  if (integrationForm.value.mattermost_bot_token_input.trim()) {
    payload.mattermost_bot_token = integrationForm.value.mattermost_bot_token_input.trim()
  }
  return payload
}

async function handleSaveIntegration() {
  const valid = await integrationFormRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) {
    return
  }

  integrationSaving.value = true
  try {
    syncFromServer(await updateMattermostIntegration(buildIntegrationPayload()))
    integrationTestState.value = null
    message.success(t('config.mattermostIntegrationSaved'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToSaveNotifications'))
  } finally {
    integrationSaving.value = false
  }
}

async function handleTestIntegration() {
  const valid = await integrationFormRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) {
    return
  }

  mattermostTesting.value = true
  try {
    const result = await testMattermostIntegration(buildIntegrationPayload())
    const text = t('config.mattermostConnectionSucceeded', {
      url: result.server_url,
      username: result.username
    })
    integrationTestState.value = { type: 'success', message: text }
    message.success(t('config.mattermostConnectionPassed'))
  } catch (error: any) {
    const detail = error?.response?.data?.detail || t('config.mattermostConnectionFailed')
    integrationTestState.value = { type: 'error', message: detail }
    message.error(detail)
  } finally {
    mattermostTesting.value = false
  }
}

async function handleClearBotToken() {
  integrationSaving.value = true
  try {
    syncFromServer(await updateMattermostIntegration({ clear_mattermost_bot_token: true }))
    integrationTestState.value = null
    message.success(t('config.mattermostBotTokenCleared'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToClearSecret'))
  } finally {
    integrationSaving.value = false
  }
}

function buildProfilePayload(): MattermostNotificationProfilePayload {
  return {
    name: profileForm.name.trim(),
    enabled: profileForm.enabled,
    target_type: profileForm.target_type,
    channel_id: profileForm.target_type === 'channel' ? profileForm.channel_id.trim() : null,
    mention_in_channel: profileForm.target_type === 'channel' ? profileForm.mention_in_channel : false,
    event_types: [...profileForm.event_types],
    field_keys: [...profileForm.field_keys]
  }
}

function setChannelLookupForm(teamName: string, channelName: string) {
  suppressChannelLookupReset.value = true
  channelLookupForm.team_name = teamName
  channelLookupForm.channel_name = channelName
  suppressChannelLookupReset.value = false
}

function clearResolvedChannelTarget(preserveLookup = true) {
  resolvedChannelTarget.value = null
  profileForm.channel_id = ''
  if (!preserveLookup) {
    setChannelLookupForm('', '')
  }
}

function applyResolvedChannelTarget(target: MattermostChannelTarget) {
  resolvedChannelTarget.value = target
  profileForm.channel_id = target.channel_id
  setChannelLookupForm(target.team_name, target.channel_name)
  profileFormRef.value?.restoreValidation?.()
}

async function handleResolveChannelTarget() {
  if (profileForm.target_type !== 'channel') {
    return
  }

  const teamName = channelLookupForm.team_name.trim()
  const channelName = channelLookupForm.channel_name.trim()
  if (!teamName || !channelName) {
    message.error(t('config.enterMattermostChannelLookupFields'))
    return
  }

  resolvingChannelTarget.value = true
  try {
    const target = await resolveMattermostChannelTarget({
      team_name: teamName,
      channel_name: channelName
    })
    applyResolvedChannelTarget(target)
    message.success(t('config.mattermostChannelTargetResolved'))
  } catch (error: any) {
    clearResolvedChannelTarget(true)
    message.error(error?.response?.data?.detail || t('config.failedToResolveMattermostChannelTarget'))
  } finally {
    resolvingChannelTarget.value = false
  }
}

async function loadChannelTarget(channelId: string) {
  const normalizedChannelId = channelId.trim()
  if (!normalizedChannelId) {
    return
  }

  loadingChannelTarget.value = true
  try {
    const target = await getMattermostChannelTarget(normalizedChannelId)
    applyResolvedChannelTarget(target)
  } catch (error: any) {
    resolvedChannelTarget.value = null
    message.error(error?.response?.data?.detail || t('config.failedToLoadMattermostChannelTarget'))
  } finally {
    loadingChannelTarget.value = false
  }
}

function openCreateProfileModal() {
  editingProfileId.value = null
  Object.assign(profileForm, createEmptyProfileForm())
  clearResolvedChannelTarget(false)
  profileModalVisible.value = true
}

function openEditProfileModal(profile: MattermostNotificationProfile) {
  editingProfileId.value = profile.id
  Object.assign(profileForm, {
    name: profile.name,
    enabled: profile.enabled,
    target_type: profile.target_type,
    channel_id: profile.channel_id || '',
    mention_in_channel: profile.mention_in_channel,
    event_types: [...profile.event_types],
    field_keys: [...profile.field_keys]
  })
  clearResolvedChannelTarget(false)
  profileModalVisible.value = true
  if (profile.target_type === 'channel' && profile.channel_id) {
    void loadChannelTarget(profile.channel_id)
  }
}

function closeProfileModal() {
  profileModalVisible.value = false
  editingProfileId.value = null
  Object.assign(profileForm, createEmptyProfileForm())
  clearResolvedChannelTarget(false)
  profileFormRef.value?.restoreValidation?.()
}

async function handleSaveProfile() {
  const valid = await profileFormRef.value?.validate().then(() => true).catch(() => false)
  if (!valid) {
    return
  }

  profileSaving.value = true
  try {
    if (editingProfileId.value === null) {
      await createMattermostNotificationProfile(buildProfilePayload())
      message.success(t('config.notificationProfileCreated'))
    } else {
      await updateMattermostNotificationProfile(editingProfileId.value, buildProfilePayload())
      message.success(t('config.notificationProfileUpdated'))
    }
    closeProfileModal()
    await fetchNotifications(false)
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToSaveNotifications'))
  } finally {
    profileSaving.value = false
  }
}

async function handleDeleteProfile(profile: MattermostNotificationProfile) {
  deletingProfileId.value = profile.id
  try {
    await deleteMattermostNotificationProfile(profile.id)
    await fetchNotifications(false)
    message.success(t('config.notificationProfileDeleted'))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.failedToDeleteNotificationProfile'))
  } finally {
    deletingProfileId.value = null
  }
}

function getTargetLabel(targetType: MattermostNotificationTargetType) {
  if (targetType === 'initiator_dm') {
    return t('config.notificationTargetInitiatorDm')
  }
  return t('config.notificationTargetChannel')
}

function getTargetSummary(profile: MattermostNotificationProfile) {
  if (profile.target_type === 'initiator_dm') {
    return t('config.notificationTargetInitiatorDmHint')
  }
  return profile.channel_id
    ? t('config.mattermostChannelIdSummary', { channelId: profile.channel_id })
    : '-'
}

function getEventLabel(eventType: MattermostNotificationEventType) {
  return (
    eventOptions.value.find((item) => item.value === eventType)?.label ||
    eventType
  )
}

function getFieldLabel(fieldKey: MattermostNotificationFieldKey) {
  return (
    fieldOptions.value.find((item) => item.value === fieldKey)?.label ||
    fieldKey
  )
}

watch(
  () => props.reloadKey,
  () => {
    fetchNotifications(false)
  },
  { immediate: true }
)

watch(
  () => profileForm.target_type,
  (targetType) => {
    if (targetType !== 'channel') {
      clearResolvedChannelTarget(false)
      profileForm.mention_in_channel = false
      profileFormRef.value?.restoreValidation?.()
    }
  }
)

watch(
  () => [channelLookupForm.team_name, channelLookupForm.channel_name],
  ([teamName, channelName]) => {
    if (suppressChannelLookupReset.value || !resolvedChannelTarget.value) {
      return
    }

    if (
      teamName.trim() !== resolvedChannelTarget.value.team_name ||
      channelName.trim() !== resolvedChannelTarget.value.channel_name
    ) {
      clearResolvedChannelTarget(true)
    }
  }
)
</script>

<style scoped>
.config-editor-modal__header {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-channel-target__hint {
  color: var(--n-text-color-3);
  font-size: 13px;
  line-height: 1.5;
}

.config-channel-target__alert {
  width: 100%;
}

.config-section-form--compact :deep(.config-form__section) {
  gap: 10px;
  margin-bottom: 20px;
}

.config-section-form--compact :deep(.config-form__section + .config-form__section) {
  padding-top: 16px;
}

.config-channel-target__grid {
  align-items: start;
}

.config-channel-target__resolve-item :deep(.n-form-item-blank) {
  width: 100%;
}

.config-channel-target__actions {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  width: 100%;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(248, 250, 252, 0.9);
}

.config-inline-toggle {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 12px 14px;
  border-radius: 14px;
  border: 1px solid rgba(148, 163, 184, 0.18);
  background: rgba(248, 250, 252, 0.9);
}

.config-inline-toggle__content {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-inline-toggle__label {
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.config-inline-toggle__hint {
  color: var(--n-text-color-3);
  font-size: 13px;
  line-height: 1.5;
}

@media (max-width: 768px) {
  .config-channel-target__actions,
  .config-inline-toggle {
    align-items: stretch;
    flex-direction: column;
  }

  .config-inline-toggle :deep(.n-switch) {
    align-self: flex-start;
  }
}
</style>
