<template>
  <div class="config-layout__main">
    <n-card id="prompt-templates-settings" class="config-form-card" :bordered="false">
      <template #header>
        <div :class="['config-card-header', { 'config-card-header--stacked': isMobile }]">
          <div>
            <div class="config-card-header__title">{{ t('config.promptTemplates') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.promptTemplatesSubtitle') }}</div>
          </div>
          <n-button
            type="primary"
            size="small"
            data-testid="prompt-template-create-button"
            @click="handleCreatePromptTemplate"
          >
            {{ t('config.createPromptTemplate') }}
          </n-button>
        </div>
      </template>

      <n-modal
        class="config-editor-modal"
        :show="promptTemplateModalVisible"
        preset="card"
        :style="{ width: isMobile ? '96vw' : '860px' }"
        data-testid="prompt-template-modal"
        @update:show="handlePromptTemplateModalVisibilityChange"
      >
        <div class="prompt-template-editor">
          <div class="prompt-template-editor__header">
            <div class="config-card-header__title">
              {{ promptTemplateEditingId ? t('config.editPromptTemplate') : t('config.createPromptTemplate') }}
            </div>
            <div class="config-card-header__subtitle">
              {{ t('config.promptTemplatesSubtitle') }}
            </div>
          </div>

          <n-form ref="promptTemplateFormRef" :model="promptTemplateForm" label-placement="top" class="config-section-form">
            <div class="config-form__section">
              <div class="config-form__section-title">{{ t('config.promptTemplateEditorSection') }}</div>
              <n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
                <n-gi>
                  <n-form-item :label="t('config.promptTemplateName')" path="name" required>
                    <n-input
                      v-model:value="promptTemplateForm.name"
                      class="config-form__input"
                      data-testid="prompt-template-name-input"
                      :placeholder="t('config.promptTemplateNamePlaceholder')"
                    />
                    <template #feedback>
                      {{ t('config.promptTemplateNameHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi>
                  <n-form-item :label="t('config.promptTemplateActive')" path="is_active">
                    <n-switch
                      v-model:value="promptTemplateForm.is_active"
                      data-testid="prompt-template-active-switch"
                    />
                    <template #feedback>
                      {{ t('config.promptTemplateActiveHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
                <n-gi :span="isMobile ? 1 : 2">
                  <n-form-item :label="t('config.promptTemplateContent')" path="content" required>
                    <VariableEditor
                      data-testid="prompt-template-content-editor"
                      v-model="promptTemplateForm.content"
                      :variable-tips="promptTemplateForm.variable_tips"
                      editable
                      @update:variable-tips="handlePromptTemplateVariableTipsUpdate"
                    />
                    <template #feedback>
                      {{ t('config.promptTemplateContentHint') }}
                    </template>
                  </n-form-item>
                </n-gi>
              </n-grid>
            </div>
          </n-form>

          <div class="config-card-actions prompt-template-editor__actions">
            <n-space justify="end">
              <n-button data-testid="prompt-template-cancel-button" @click="handleCancelPromptTemplateEditing">
                {{ t('common.cancel') }}
              </n-button>
              <n-button type="primary" data-testid="prompt-template-save-button" @click="handleSavePromptTemplate">
                {{ t('common.save') }}
              </n-button>
            </n-space>
          </div>
        </div>
      </n-modal>

      <div v-if="!isMobile" class="config-table-wrapper prompt-template-table-wrapper">
        <n-data-table
          data-testid="prompt-template-table"
          :columns="promptTemplateColumns"
          :data="promptTemplates"
          :loading="promptTemplatesLoading"
          :row-key="(row: PromptTemplate) => row.id"
          :pagination="false"
          :bordered="false"
          :scroll-x="960"
        />
      </div>

      <n-spin v-else :show="promptTemplatesLoading">
        <div v-if="!promptTemplatesLoading && promptTemplates.length === 0" class="config-empty" data-testid="prompt-template-empty">
          {{ t('config.promptTemplateEmpty') }}
        </div>
        <div v-for="template in promptTemplates" :key="template.id" class="prompt-template-mobile__item" :data-testid="`prompt-template-card-${template.id}`">
          <div class="prompt-template-mobile__top">
            <div>
              <div class="prompt-template-mobile__title">{{ template.name }}</div>
              <div class="prompt-template-mobile__meta">{{ new Date(template.updated_at).toLocaleString() }}</div>
            </div>
            <n-tag :type="template.is_active ? 'success' : 'default'" round>
              {{ template.is_active ? t('common.enabled') : t('common.disabled') }}
            </n-tag>
          </div>
          <div class="prompt-template-mobile__content">{{ template.content }}</div>
          <div class="prompt-template-mobile__actions">
            <n-button
              size="small"
              :data-testid="getPromptTemplateEditButtonTestId(template.id)"
              @click="handleEditPromptTemplate(template)"
            >
              {{ t('common.edit') }}
            </n-button>
            <n-popconfirm
              :positive-text="t('common.delete')"
              :negative-text="t('common.cancel')"
              :internal-extra-class="[getPromptTemplateDeleteConfirmButtonTestId(template.id)]"
              @positive-click="handleDeletePromptTemplate(template.id)"
            >
              <template #trigger>
                <n-button
                  size="small"
                  type="error"
                  :data-testid="getPromptTemplateDeleteButtonTestId(template.id)"
                >
                  {{ t('common.delete') }}
                </n-button>
              </template>
              {{ t('config.promptTemplateDeleteConfirm') }}
            </n-popconfirm>
          </div>
        </div>
      </n-spin>
    </n-card>
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
  NGi,
  NGrid,
  NInput,
  NPopconfirm,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  NModal,
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

const props = withDefaults(defineProps<{
  isMobile?: boolean
}>(), {
  isMobile: false
})

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

const isMobile = computed(() => props.isMobile)

function getPromptTemplateEditButtonTestId(id: number) {
  return `prompt-template-edit-button-${id}`
}

function getPromptTemplateDeleteButtonTestId(id: number) {
  return `prompt-template-delete-button-${id}`
}

function getPromptTemplateDeleteConfirmButtonTestId(id: number) {
  return `prompt-template-delete-popconfirm-${id}`
}

function areTipsEqual(
  left: Record<string, string> | undefined,
  right: Record<string, string> | undefined
) {
  const leftEntries = Object.entries(left ?? {}).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))
  const rightEntries = Object.entries(right ?? {}).sort(([leftKey], [rightKey]) => leftKey.localeCompare(rightKey))

  if (leftEntries.length !== rightEntries.length) {
    return false
  }

  return leftEntries.every(([key, value], index) => {
    const [otherKey, otherValue] = rightEntries[index] ?? []
    return key === otherKey && value === otherValue
  })
}

function handlePromptTemplateVariableTipsUpdate(tips: Record<string, string>) {
  if (areTipsEqual(tips, promptTemplateForm.variable_tips)) {
    return
  }

  promptTemplateForm.variable_tips = { ...tips }
}

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
    render: (row: PromptTemplate) =>
      h(
        'div',
        { class: 'prompt-template-content-preview' },
        row.content.substring(0, 100) + (row.content.length > 100 ? '...' : '')
      )
  },
  {
    title: t('config.promptTemplateActive'),
    key: 'is_active',
    width: 100,
    render: (row: PromptTemplate) =>
      h(NTag, { type: row.is_active ? 'success' : 'default', round: true }, {
        default: () => row.is_active ? t('common.enabled') : t('common.disabled')
      })
  },
  {
    title: t('config.promptTemplateUpdatedAt'),
    key: 'updated_at',
    width: 180,
    render: (row: PromptTemplate) => new Date(row.updated_at).toLocaleString()
  },
  {
    title: t('config.actions'),
    key: 'actions',
    width: 160,
    render: (row: PromptTemplate) =>
      h(NSpace, { size: 'small' }, {
        default: () => [
          h(NButton, {
            size: 'small',
            'data-testid': getPromptTemplateEditButtonTestId(row.id),
            onClick: () => handleEditPromptTemplate(row)
          }, { default: () => t('common.edit') }),
          h(NPopconfirm, {
            positiveText: t('common.delete'),
            negativeText: t('common.cancel'),
            internalExtraClass: [getPromptTemplateDeleteConfirmButtonTestId(row.id)],
            onPositiveClick: () => handleDeletePromptTemplate(row.id)
          }, {
            trigger: () =>
              h(NButton, {
                size: 'small',
                type: 'error',
                'data-testid': getPromptTemplateDeleteButtonTestId(row.id)
              }, { default: () => t('common.delete') }),
            default: () => t('config.promptTemplateDeleteConfirm')
          })
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

function resetPromptTemplateForm() {
  promptTemplateEditingId.value = null
  promptTemplateForm.name = ''
  promptTemplateForm.content = ''
  promptTemplateForm.variable_tips = {}
  promptTemplateForm.is_active = true
}

function handleCreatePromptTemplate() {
  resetPromptTemplateForm()
  promptTemplateModalVisible.value = true
}

function handleEditPromptTemplate(template: PromptTemplate) {
  promptTemplateEditingId.value = template.id
  promptTemplateForm.name = template.name
  promptTemplateForm.content = template.content
  promptTemplateForm.variable_tips = template.variable_tips ? { ...template.variable_tips } : {}
  promptTemplateForm.is_active = template.is_active
  promptTemplateModalVisible.value = true
  promptTemplateFormRef.value?.restoreValidation?.()
}

function handleCancelPromptTemplateEditing() {
  promptTemplateModalVisible.value = false
  resetPromptTemplateForm()
  promptTemplateFormRef.value?.restoreValidation?.()
}

function handlePromptTemplateModalVisibilityChange(show: boolean) {
  if (show) {
    promptTemplateModalVisible.value = true
    return
  }
  handleCancelPromptTemplateEditing()
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
    handleCancelPromptTemplateEditing()
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

<style scoped>
.prompt-template-editor {
  margin-bottom: 20px;
  padding: 18px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 16px;
  background: rgba(248, 250, 252, 0.82);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.65);
}

.prompt-template-editor__header {
  margin-bottom: 16px;
}

.prompt-template-editor__actions {
  margin-top: 0;
}

.prompt-template-table-wrapper {
  margin-top: 0;
}

.prompt-template-mobile__item {
  margin-bottom: 8px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 250, 252, 0.8);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
}

.prompt-template-mobile__top,
.prompt-template-mobile__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.prompt-template-mobile__title {
  font-size: 15px;
  font-weight: 600;
  color: #0f172a;
}

.prompt-template-mobile__meta {
  margin-top: 4px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.58);
}

.prompt-template-mobile__content {
  margin: 12px 0;
  font-size: 13px;
  line-height: 1.6;
  color: rgba(15, 23, 42, 0.72);
  word-break: break-word;
}

.prompt-template-mobile__actions {
  justify-content: flex-end;
}
</style>
