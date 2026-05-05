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
          :scroll-x="820"
        />
      </div>
    </n-card>

    <n-modal
      class="config-editor-modal"
      :show="modalVisible"
      preset="card"
      :style="{ width: isMobile ? '96vw' : '560px' }"
      @update:show="handleModalVisibilityChange"
    >
      <template #header>
        <div>{{ editingProvider ? t('config.providers.edit') : t('config.providers.create') }}</div>
      </template>

      <n-form
        ref="formRef"
        :model="formValue"
        :rules="rules"
        label-placement="top"
        class="config-section-form ai-provider-modal__form"
      >
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
            placeholder="claude-sonnet-4-20250514"
            class="config-form__input"
          />
          <template #feedback>
            {{ t('config.providers.modelHint') }}
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
            :rows="4"
            :placeholder="t('config.providers.systemPromptHint')"
            class="config-form__input"
          />
        </n-form-item>
      </n-form>

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
  NSpace,
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
  system_prompt: ''
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
        maxWidth: 420,
        style: { maxWidth: '420px', wordBreak: 'break-word', whiteSpace: 'pre-wrap' }
      }
    },
    render: (row: AIProvider) =>
      row.system_prompt
        ? h('span', { class: 'ai-providers-system-prompt-preview' }, row.system_prompt)
        : h('span', { style: 'color: rgba(15,23,42,0.38)' }, '—')
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 220,
    render: (row: AIProvider) =>
      h(NSpace, { size: 'small', wrap: false }, {
        default: () => [
          h(NButton, {
            size: 'small',
            onClick: () => openEdit(row)
          }, { default: () => t('common.edit') }),
          !row.is_default
            ? h(NButton, {
                size: 'small',
                onClick: () => handleSetDefault(row)
              }, { default: () => t('config.providers.setDefault') })
            : null,
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
    system_prompt: ''
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
    system_prompt: provider.system_prompt || ''
  }
  modalVisible.value = true
  clearFormValidation()
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
        max_turns: formValue.value.max_turns
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
        max_turns: formValue.value.max_turns
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

.ai-provider-modal__form {
  gap: 14px;
}

.ai-provider-modal__form :deep(.n-form-item) {
  margin-bottom: 0;
}

.ai-provider-modal__form :deep(.n-form-item-feedback-wrapper) {
  min-height: auto;
  padding-top: 6px;
}
</style>
