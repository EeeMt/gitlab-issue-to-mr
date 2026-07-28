import { computed, ref, type Ref } from 'vue'
import { useI18n } from 'vue-i18n'

import {
  getProviders,
  getSkills,
  getWorkerProfiles,
  type AIProvider,
  type Task,
  type SkillOption,
  type WorkerProfile,
} from '../../api'

interface TaskExecutionOptions {
  mode: Readonly<Ref<'create' | 'edit'>>
  task: Readonly<Ref<Task | undefined>>
  defaultProviderId: Readonly<Ref<number | null | undefined>>
  workerProfileId: Readonly<Ref<number | null | undefined>>
  selectedProviderId: Ref<number | null>
}

export function useTaskExecutionOptions(options: TaskExecutionOptions) {
  const { t } = useI18n()
  const providers = ref<AIProvider[]>([])
  const workerProfiles = ref<WorkerProfile[]>([])
  const skills = ref<SkillOption[]>([])
  const skillsLoadSucceeded = ref(false)

  const selectableProviders = computed(() =>
    providers.value.filter(provider =>
      !provider.is_disabled
      || (options.mode.value === 'edit' && provider.id === options.task.value?.provider_id)
    )
  )
  const providerOptions = computed(() =>
    selectableProviders.value.map(provider => ({
      label: `${provider.name} (${provider.model})${provider.is_default ? ' ★' : ''}${provider.is_disabled ? ` - ${t('config.providers.disabled')}` : ''}`,
      value: provider.id,
      disabled: provider.is_disabled,
    }))
  )
  const skillOptions = computed(() =>
    skills.value.map(skill => ({
      label: skill.name,
      value: skill.id,
      disabled: false,
    }))
  )
  const selectableWorkerProfiles = computed(() =>
    workerProfiles.value.filter(profile =>
      profile.enabled
      || (
        options.mode.value === 'edit'
        && profile.id === options.task.value?.worker_profile_id
      )
    )
  )

  const effectiveProvider = computed(() => {
    if (options.selectedProviderId.value !== null) {
      return selectableProviders.value.find(
        provider => provider.id === options.selectedProviderId.value,
      ) ?? null
    }
    if (options.defaultProviderId.value != null) {
      return selectableProviders.value.find(
        provider => provider.id === options.defaultProviderId.value,
      ) ?? null
    }
    return selectableProviders.value.find(
      provider => provider.is_default && !provider.is_disabled,
    ) ?? null
  })

  const effectiveWorkerProfile = computed(() => {
    const workerProfileId = options.workerProfileId.value ?? options.task.value?.worker_profile_id
    if (workerProfileId != null) {
      return selectableWorkerProfiles.value.find(
        profile => profile.id === workerProfileId,
      ) ?? null
    }
    return null
  })

  async function loadProviders() {
    try {
      providers.value = await getProviders()
    } catch {
      providers.value = []
    }
  }

  async function loadWorkerProfiles() {
    try {
      workerProfiles.value = await getWorkerProfiles()
    } catch {
      workerProfiles.value = []
    }
  }

  async function loadSkills() {
    skillsLoadSucceeded.value = false
    try {
      skills.value = await getSkills()
      skillsLoadSucceeded.value = true
    } catch {
      skills.value = []
    }
  }

  return {
    effectiveProvider,
    effectiveWorkerProfile,
    loadProviders,
    loadSkills,
    loadWorkerProfiles,
    providerOptions,
    skillOptions,
    skills,
    skillsLoadSucceeded,
    selectableProviders,
    selectableWorkerProfiles,
    workerProfiles,
  }
}
