<template>
  <div class="config-layout__main">
    <n-card class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.providers.title') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.providers.subtitle') }}</div>
          </div>
        </div>
      </template>
      <template #header-extra>
        <n-button type="primary" size="small" @click="openCreate">
          {{ t('config.providers.create') }}
        </n-button>
      </template>

      <div class="config-table-wrapper">
        <n-data-table
          :columns="columns"
          :data="providers"
          :loading="loading"
          :bordered="false"
          size="small"
          :scroll-x="1120"
        />
      </div>
    </n-card>

    <n-modal
      class="config-editor-modal"
      :show="modalVisible"
      preset="card"
      :style="{ width: isMobile ? '96vw' : 'min(880px, calc(100vw - 32px))' }"
      @update:show="handleModalVisibilityChange"
    >
      <template #header>
        <div class="ai-provider-modal__header">
          <div class="ai-provider-modal__title">
            {{ editingProvider ? t('config.providers.edit') : t('config.providers.create') }}
          </div>
          <div v-if="editingProvider" class="ai-provider-modal__subtitle">
            {{ editingProvider.name }} / {{ editingProvider.model }}
          </div>
        </div>
      </template>

      <div class="config-editor-modal__scroll ai-provider-modal__scroll">
        <n-form
          ref="formRef"
          :model="formValue"
          :rules="rules"
          label-placement="top"
          class="config-section-form ai-provider-modal__form"
        >
          <div class="ai-provider-modal__grid">
            <n-form-item :label="t('config.providers.name')" path="name">
              <n-input
                v-model:value="formValue.name"
                placeholder="my-provider"
                class="config-form__input"
              />
              <template #feedback>
                {{ t('config.providers.nameHint') }}
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.maxTurns')" path="max_turns">
              <n-input-number
                v-model:value="formValue.max_turns"
                :min="1"
                :max="1000"
                class="config-form__input"
              />
              <template #feedback>
                {{ t('config.providers.maxTurnsHint') }}
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.baseUrl')" path="base_url">
              <n-input
                v-model:value="formValue.base_url"
                placeholder="http://host.docker.internal:11434/v1"
                class="config-form__input"
              />
              <template #feedback>
                {{ t('config.providers.baseUrlHint') }}
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.model')" path="model">
              <n-input
                v-model:value="formValue.model"
                placeholder="my-model"
                class="config-form__input"
              />
              <template #feedback>
                {{ t('config.providers.modelHint') }}
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.providerKind')" path="provider_kind">
              <n-select
                v-model:value="formValue.provider_kind"
                :options="providerKindOptions"
                class="config-form__input"
                @update:value="handleProviderKindChange"
              />
              <template #feedback>
                {{ t('config.providers.providerKindHint') }}
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.wireProtocol')" path="model_protocol">
              <n-select
                v-model:value="formValue.model_protocol"
                :options="wireProtocolOptions"
                class="config-form__input"
                @update:value="handleModelProtocolChange"
              />
              <template #feedback>
                {{ t('config.providers.wireProtocolHint') }}
              </template>
            </n-form-item>
          </div>

          <div class="ai-provider-modal__section">
            <n-form-item :label="t('config.providers.apiKey')" path="api_key">
              <n-input
                v-model:value="formValue.api_key"
                type="password"
                show-password-on="click"
                :placeholder="editingProvider ? t('config.providers.apiKeyHint') : ''"
                class="config-form__input"
              />
              <template #feedback>
                <span v-if="editingProvider && editingProvider.api_key_configured">
                  <n-tag size="tiny" type="success" round>{{ t('config.providers.apiKeyConfigured') }}</n-tag>
                </span>
                <span v-else-if="editingProvider">
                  <n-tag size="tiny" type="warning" round>{{ t('config.providers.apiKeyNotConfigured') }}</n-tag>
                </span>
              </template>
            </n-form-item>

            <n-form-item :label="t('config.providers.systemPrompt')" path="system_prompt">
              <n-input
                v-model:value="formValue.system_prompt"
                type="textarea"
                :rows="5"
                :placeholder="t('config.providers.systemPromptHint')"
                class="config-form__input ai-provider-modal__textarea"
              />
            </n-form-item>
          </div>

          <div class="ai-provider-modal__status">
            <n-form-item :label="t('config.providers.status')" path="is_disabled">
              <n-switch
                :value="!formValue.is_disabled"
                :disabled="editingProvider?.is_default"
                @update:value="handleStatusSwitchChange"
              >
                <template #checked>{{ t('config.providers.enabled') }}</template>
                <template #unchecked>{{ t('config.providers.disabled') }}</template>
              </n-switch>
              <template #feedback>
                {{ t('config.providers.disabledHint') }}
              </template>
            </n-form-item>
          </div>
        </n-form>
      </div>

      <template #footer>
        <n-space justify="end">
          <n-button @click="closeModal">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" :loading="saving" @click="handleSave">
            {{ t('common.save') }}
          </n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NModal,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
  type DataTableColumns,
  type FormInst,
  type FormRules
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import {
  getProviders,
  createProvider,
  updateProvider,
  deleteProvider,
  setDefaultProvider,
  type AIProvider,
  type CreateProviderRequest,
  type UpdateProviderRequest
} from '../../api'

const PROVIDER_KIND_PROTOCOLS: Record<string, string[]> = {
  anthropic_compatible: ['anthropic_messages'],
  openai_compatible: ['openai_responses', 'openai_chat_completions'],
}

const PROVIDER_KIND_DEFAULT_PROTOCOL: Record<string, string> = {
  anthropic_compatible: 'anthropic_messages',
  openai_compatible: 'openai_responses',
}

const MODEL_PROTOCOL_PROVIDER_KIND: Record<string, string> = {
  anthropic_messages: 'anthropic_compatible',
  openai_responses: 'openai_compatible',
  openai_chat_completions: 'openai_compatible',
}

defineProps<{
  isMobile: boolean
}>()

const { t } = useI18n()
const message = useMessage()

// State
const providers = ref<AIProvider[]>([])
const loading = ref(false)
const saving = ref(false)
const modalVisible = ref(false)
const editingProvider = ref<AIProvider | null>(null)
const formRef = ref<FormInst | null>(null)

const formValue = ref({
  name: '',
  base_url: '',
  model: '',
  max_turns: 20,
  api_key: '',
  system_prompt: '',
  provider_kind: 'anthropic_compatible',
  model_protocol: 'anthropic_messages',
  is_disabled: false
})

const providerKindOptions = computed(() => [
  { label: t('config.providers.providerKindAnthropic'), value: 'anthropic_compatible' },
  { label: t('config.providers.providerKindOpenai'), value: 'openai_compatible' },
])

const wireProtocolOptions = computed(() => {
  return Object.keys(MODEL_PROTOCOL_PROVIDER_KIND).map(protocol => ({
    label: protocol === 'anthropic_messages'
      ? t('config.providers.wireProtocolAnthropicMessages')
      : protocol === 'openai_responses'
        ? t('config.providers.wireProtocolOpenaiResponses')
        : t('config.providers.wireProtocolOpenaiChatCompletions'),
    value: protocol,
  }))
})

const rules: FormRules = {
  name: [
    {
      required: true,
      message: () => t('config.providers.nameHint'),
      trigger: 'blur'
    },
    {
      pattern: /^[a-zA-Z0-9_-]+$/,
      message: () => t('config.providers.nameHint'),
      trigger: 'blur'
    }
  ],
  base_url: [
    {
      required: true,
      message: () => t('config.providers.baseUrlHint'),
      trigger: 'blur'
    },
    {
      pattern: /^https?:\/\//,
      message: () => t('config.providers.baseUrlHint'),
      trigger: 'blur'
    }
  ],
  model: {
    required: true,
    message: () => t('config.providers.modelHint'),
    trigger: 'blur'
  },
  max_turns: {
    required: true,
    type: 'number',
    min: 1,
    max: 1000,
    message: () => t('config.providers.maxTurnsHint'),
    trigger: 'blur'
  }
}

// Columns
const columns = computed<DataTableColumns<AIProvider>>(() => [
  {
    title: t('config.providers.name'),
    key: 'name',
    minWidth: 140,
    render: (row: AIProvider) =>
      h(NSpace, { size: 'small', align: 'center' }, {
        default: () => [
          h('span', { style: 'font-weight: 600' }, row.name),
          row.is_default
            ? h(NTag, { type: 'info', size: 'small', round: true }, { default: () => t('config.providers.isDefault') })
            : null
        ]
      })
  },
  {
    title: t('config.providers.status'),
    key: 'is_disabled',
    width: 100,
    render: (row: AIProvider) =>
      h(NTag, {
        type: row.is_disabled ? 'warning' : 'success',
        size: 'small',
        round: true
      }, {
        default: () => row.is_disabled ? t('config.providers.disabled') : t('config.providers.enabled')
      })
  },
  {
    title: t('config.providers.model'),
    key: 'model',
    minWidth: 160,
    ellipsis: { tooltip: true }
  },
  {
    title: t('config.providers.baseUrl'),
    key: 'base_url',
    minWidth: 160,
    ellipsis: { tooltip: true }
  },
  {
    title: t('config.providers.maxTurns'),
    key: 'max_turns',
    width: 90
  },
  {
    title: t('config.providers.apiKey'),
    key: 'api_key_configured',
    width: 110,
    render: (row: AIProvider) =>
      h(NTag, {
        type: row.api_key_configured ? 'success' : 'warning',
        size: 'small',
        round: true
      }, {
        default: () =>
          row.api_key_configured
            ? t('config.providers.apiKeyConfigured')
            : t('config.providers.apiKeyNotConfigured')
      })
  },
  {
    title: t('config.providers.systemPrompt'),
    key: 'system_prompt',
    minWidth: 120,
    ellipsis: {
      tooltip: {
        style: { maxWidth: '420px', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      } as any
    },
    render: (row: AIProvider) =>
      row.system_prompt
        ? h('span', { class: 'ai-providers-system-prompt-preview' }, row.system_prompt)
        : h('span', { style: 'color: rgba(15,23,42,0.38)' }, '—')
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 280,
    render: (row: AIProvider) =>
      h(NSpace, { size: 'small', wrap: false }, {
        default: () => [
          h(NButton, {
            size: 'small',
            onClick: () => openEdit(row)
          }, { default: () => t('common.edit') }),
          h(NButton, {
            size: 'small',
            disabled: row.is_default,
            onClick: () => handleToggleDisabled(row)
          }, { default: () => row.is_disabled ? t('config.providers.enable') : t('config.providers.disable') }),
          h(NButton, {
            size: 'small',
            disabled: row.is_default || row.is_disabled,
            onClick: () => handleSetDefault(row)
          }, { default: () => t('config.providers.setDefault') }),
          h(NPopconfirm, {
            positiveText: t('common.delete'),
            negativeText: t('common.cancel'),
            onPositiveClick: () => handleDelete(row)
          }, {
            trigger: () =>
              h(NButton, {
                size: 'small',
                type: 'error',
                disabled: row.is_default && providers.value.length === 1
              }, { default: () => t('common.delete') }),
            default: () => row.is_default && providers.value.length === 1
              ? t('config.providers.deleteLast')
              : t('config.providers.deleteConfirm')
          })
        ]
      })
  }
])

// Fetch
async function fetchProviders() {
  loading.value = true
  try {
    providers.value = await getProviders()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to load providers')
  } finally {
    loading.value = false
  }
}

// Create / Edit drawer
function resetForm() {
  formValue.value = {
    name: '',
    base_url: '',
    model: '',
    max_turns: 20,
    api_key: '',
    system_prompt: '',
    provider_kind: 'anthropic_compatible',
    model_protocol: 'anthropic_messages',
    is_disabled: false
  }
}

function clearFormValidation() {
  formRef.value?.restoreValidation?.()
}

function closeModal() {
  modalVisible.value = false
  editingProvider.value = null
  resetForm()
  clearFormValidation()
}

function handleModalVisibilityChange(show: boolean) {
  if (show) {
    modalVisible.value = true
    return
  }
  closeModal()
}

function openCreate() {
  modalVisible.value = true
  editingProvider.value = null
  resetForm()
  clearFormValidation()
}

function openEdit(provider: AIProvider) {
  editingProvider.value = provider
  formValue.value = {
    name: provider.name,
    base_url: provider.base_url,
    model: provider.model,
    max_turns: provider.max_turns,
    api_key: '',
    system_prompt: provider.system_prompt || '',
    provider_kind: provider.provider_kind || 'anthropic_compatible',
    model_protocol: provider.model_protocol || 'anthropic_messages',
    is_disabled: provider.is_disabled
  }
  modalVisible.value = true
  clearFormValidation()
}

function handleStatusSwitchChange(isEnabled: boolean) {
  formValue.value.is_disabled = !isEnabled
}

function handleProviderKindChange(kind: string) {
  formValue.value.provider_kind = kind
  const protocols = PROVIDER_KIND_PROTOCOLS[kind] ?? []
  if (!protocols.includes(formValue.value.model_protocol)) {
    formValue.value.model_protocol =
      PROVIDER_KIND_DEFAULT_PROTOCOL[kind] ?? protocols[0] ?? 'anthropic_messages'
  }
}

function handleModelProtocolChange(protocol: string) {
  formValue.value.model_protocol = protocol
  const providerKind = MODEL_PROTOCOL_PROVIDER_KIND[protocol]
  if (providerKind && formValue.value.provider_kind !== providerKind) {
    formValue.value.provider_kind = providerKind
  }
}

async function handleSave() {
  if (!formRef.value) return
  try {
    await formRef.value.validate()
  } catch {
    return
  }

  saving.value = true
  try {
    if (editingProvider.value) {
      // Update existing
      const req: UpdateProviderRequest = {
        name: formValue.value.name.trim(),
        base_url: formValue.value.base_url.trim(),
        model: formValue.value.model.trim(),
        max_turns: formValue.value.max_turns,
        provider_kind: formValue.value.provider_kind,
        model_protocol: formValue.value.model_protocol,
        provider_driver: editingProvider.value.provider_driver,
        is_disabled: formValue.value.is_disabled
      }
      if (formValue.value.api_key.trim()) {
        req.api_key = formValue.value.api_key.trim()
      }
      if (formValue.value.system_prompt.trim()) {
        req.system_prompt = formValue.value.system_prompt.trim()
      } else {
        req.clear_system_prompt = true
      }
      await updateProvider(editingProvider.value.id, req)
      message.success(t('config.providers.updated'))
    } else {
      // Create new
      const req: CreateProviderRequest = {
        name: formValue.value.name.trim(),
        base_url: formValue.value.base_url.trim(),
        model: formValue.value.model.trim(),
        max_turns: formValue.value.max_turns,
        provider_kind: formValue.value.provider_kind,
        model_protocol: formValue.value.model_protocol,
        is_disabled: formValue.value.is_disabled
      }
      if (formValue.value.api_key.trim()) {
        req.api_key = formValue.value.api_key.trim()
      }
      if (formValue.value.system_prompt.trim()) {
        req.system_prompt = formValue.value.system_prompt.trim()
      }
      await createProvider(req)
      message.success(t('config.providers.created'))
    }

    closeModal()
    await fetchProviders()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  } finally {
    saving.value = false
  }
}

async function handleToggleDisabled(provider: AIProvider) {
  if (provider.is_default) return
  try {
    await updateProvider(provider.id, { is_disabled: !provider.is_disabled })
    message.success(t('config.providers.updated'))
    await fetchProviders()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.saveError'))
  }
}

async function handleDelete(provider: AIProvider) {
  try {
    await deleteProvider(provider.id)
    message.success(t('config.providers.deleted'))
    await fetchProviders()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.providers.deleteBlocked'))
  }
}

async function handleSetDefault(provider: AIProvider) {
  try {
    await setDefaultProvider(provider.id)
    message.success(t('config.providers.defaultSet'))
    await fetchProviders()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || 'Failed to set default provider')
  }
}

onMounted(() => {
  fetchProviders()
})
</script>

<style scoped>
.ai-providers-system-prompt-preview {
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 12px;
}

.ai-provider-modal__header {
  display: grid;
  gap: 4px;
}

.ai-provider-modal__title {
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
  color: #0f172a;
}

.ai-provider-modal__subtitle {
  max-width: 560px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12px;
  font-weight: 400;
  line-height: 1.4;
  color: rgba(15, 23, 42, 0.54);
}

.ai-provider-modal__scroll {
  max-height: min(68vh, 640px);
}

.ai-provider-modal__form {
  gap: 18px;
}

.ai-provider-modal__grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  column-gap: 20px;
  row-gap: 14px;
}

.ai-provider-modal__section {
  display: grid;
  gap: 14px;
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.ai-provider-modal__status {
  padding-top: 16px;
  border-top: 1px solid rgba(148, 163, 184, 0.18);
}

.ai-provider-modal__form :deep(.n-form-item) {
  margin-bottom: 0;
}

.ai-provider-modal__grid :deep(.n-form-item--top-labelled) {
  grid-template-rows: auto auto auto;
  align-content: start;
}

.ai-provider-modal__grid :deep(.n-form-item) {
  align-self: start;
  min-width: 0;
}

.ai-provider-modal__form :deep(.n-form-item-feedback-wrapper) {
  min-height: auto;
  padding-top: 6px;
}

.ai-provider-modal__status :deep(.n-form-item-blank) {
  min-height: auto;
}

.ai-provider-modal__textarea :deep(textarea) {
  min-height: 132px;
  resize: vertical;
}

@media (max-width: 767px) {
  .ai-provider-modal__grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .ai-provider-modal__subtitle {
    max-width: calc(96vw - 96px);
  }

  .ai-provider-modal__scroll {
    max-height: min(72vh, 620px);
  }
}
</style>
