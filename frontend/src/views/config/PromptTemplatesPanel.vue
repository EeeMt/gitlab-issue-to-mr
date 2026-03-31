<template>
  <div class="config-layout__main">
    <n-card id="prompt-templates-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.promptTemplates') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.promptTemplatesSubtitle') }}</div>
          </div>
          <n-button type="primary" @click="handleCreatePromptTemplate" size="small">
            {{ t('config.createPromptTemplate') }}
          </n-button>
        </div>
      </template>

      <n-data-table
        :columns="promptTemplateColumns"
        :data="promptTemplates"
        :loading="promptTemplatesLoading"
        :row-key="(row: PromptTemplate) => row.id"
        :pagination="false"
        :bordered="false"
      />
    </n-card>

    <!-- Prompt Template Edit Modal -->
    <n-modal
      v-model:show="promptTemplateModalVisible"
      preset="card"
      :title="promptTemplateEditingId ? t('config.editPromptTemplate') : t('config.createPromptTemplate')"
      style="width: 600px; max-width: 90vw;"
      :mask-closable="false"
    >
      <n-form ref="promptTemplateFormRef" :model="promptTemplateForm" label-placement="top">
        <n-form-item :label="t('config.promptTemplateName')" path="name" required>
          <n-input v-model:value="promptTemplateForm.name" :placeholder="t('config.promptTemplateNamePlaceholder')" />
        </n-form-item>
        <n-form-item :label="t('config.promptTemplateContent')" path="content" required>
          <VariableEditor
            v-model="promptTemplateForm.content"
            :variable-tips="promptTemplateForm.variable_tips"
            editable
            @update:variable-tips="(tips) => promptTemplateForm.variable_tips = tips"
          />
        </n-form-item>
        <n-form-item :label="t('config.promptTemplateActive')" path="is_active">
          <n-switch v-model:value="promptTemplateForm.is_active" />
        </n-form-item>
      </n-form>
      <template #footer>
        <n-space justify="end">
          <n-button @click="promptTemplateModalVisible = false">{{ t('common.cancel') }}</n-button>
          <n-button type="primary" @click="handleSavePromptTemplate">{{ t('common.save') }}</n-button>
        </n-space>
      </template>
    </n-modal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NDataTable,
  NForm,
  NFormItem,
  NInput,
  NModal,
  NSpace,
  NSwitch,
  NTag,
  type DataTableColumns,
  type FormInst
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import {
  createPromptTemplate,
  deletePromptTemplate,
  getPromptTemplates,
  updatePromptTemplate,
  type PromptTemplate
} from '../../api'
import VariableEditor from '../../components/VariableEditor.vue'

const { t } = useI18n()
const message = useMessage()

// Prompt Templates state
const promptTemplates = ref<PromptTemplate[]>([])
const promptTemplatesLoading = ref(false)
const promptTemplateModalVisible = ref(false)
const promptTemplateEditingId = ref<number | null>(null)
const promptTemplateFormRef = ref<FormInst | null>(null)
const promptTemplateForm = reactive({
  name: '',
  content: '',
  variable_tips: {} as Record<string, string>,
  is_active: true
})

// Table columns
const promptTemplateColumns = computed<DataTableColumns<PromptTemplate>>(() => [
  {
    title: t('config.promptTemplateName'),
    key: 'name',
    minWidth: 200
  },
  {
    title: t('config.promptTemplateContent'),
    key: 'content',
    ellipsis: true,
    render: (row) => h('div', { class: 'prompt-template-content-preview' }, row.content.substring(0, 100) + (row.content.length > 100 ? '...' : ''))
  },
  {
    title: t('config.promptTemplateActive'),
    key: 'is_active',
    width: 100,
    render: (row) => h(NTag, { type: row.is_active ? 'success' : 'default', round: true }, { default: () => row.is_active ? t('common.enabled') : t('common.disabled') })
  },
  {
    title: t('config.promptTemplateUpdatedAt'),
    key: 'updated_at',
    width: 180,
    render: (row) => new Date(row.updated_at).toLocaleString()
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 160,
    render: (row) =>
      h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, { size: 'small', onClick: () => handleEditPromptTemplate(row) }, { default: () => t('common.edit') }),
          h(NButton, { size: 'small', type: 'error', onClick: () => handleDeletePromptTemplate(row.id) }, { default: () => t('common.delete') })
        ]
      })
  }
])

// Actions
async function fetchPromptTemplates() {
  try {
    promptTemplatesLoading.value = true
    promptTemplates.value = await getPromptTemplates()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.fetchPromptTemplatesFailed'))
  } finally {
    promptTemplatesLoading.value = false
  }
}

function handleCreatePromptTemplate() {
  promptTemplateEditingId.value = null
  promptTemplateForm.name = ''
  promptTemplateForm.content = ''
  promptTemplateForm.variable_tips = {}
  promptTemplateForm.is_active = true
  promptTemplateModalVisible.value = true
}

function handleEditPromptTemplate(template: PromptTemplate) {
  promptTemplateEditingId.value = template.id
  promptTemplateForm.name = template.name
  promptTemplateForm.content = template.content
  promptTemplateForm.variable_tips = template.variable_tips ? { ...template.variable_tips } : {}
  promptTemplateForm.is_active = template.is_active
  promptTemplateModalVisible.value = true
}

async function handleSavePromptTemplate() {
  const currentContent = promptTemplateForm.content || ''
  const currentTips = { ...promptTemplateForm.variable_tips }

  // Validate: extract variables from content and check for orphan tips
  const contentMatches = currentContent.match(/\{\{([^}]+)\}\}/g) || []
  const contentVars = new Set(contentMatches.map((m: string) => m.replace(/\{\{|\}\}/g, '')))
  const tipKeys = Object.keys(currentTips)

  // Find tips that don't have corresponding variables in content
  const invalidTips = tipKeys.filter(varName => !contentVars.has(varName))

  if (invalidTips.length > 0) {
    message.warning(t('config.promptTemplateInvalidTips', { variables: invalidTips.join(', ') }))
    return
  }

  try {
    if (promptTemplateEditingId.value) {
      await updatePromptTemplate(promptTemplateEditingId.value, {
        name: promptTemplateForm.name,
        content: currentContent,
        variable_tips: currentTips,
        is_active: promptTemplateForm.is_active
      })
      message.success(t('config.updatePromptTemplateSuccess'))
    } else {
      await createPromptTemplate({
        name: promptTemplateForm.name,
        content: currentContent,
        variable_tips: currentTips,
        is_active: promptTemplateForm.is_active
      })
      message.success(t('config.createPromptTemplateSuccess'))
    }
    promptTemplateModalVisible.value = false
    await fetchPromptTemplates()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.savePromptTemplateFailed'))
  }
}

async function handleDeletePromptTemplate(id: number) {
  try {
    await deletePromptTemplate(id)
    message.success(t('config.deletePromptTemplateSuccess'))
    await fetchPromptTemplates()
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.deletePromptTemplateFailed'))
  }
}

// Expose for parent to trigger initial fetch
defineExpose({
  fetchPromptTemplates
})
</script>
