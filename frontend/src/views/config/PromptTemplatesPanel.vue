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
        <template #header>
          <div class="prompt-template-modal__header">
            <div class="config-card-header__title">
              {{ promptTemplateEditingId ? t('config.editPromptTemplate') : t('config.createPromptTemplate') }}
            </div>
            <div class="config-card-header__subtitle">
              {{ t('config.promptTemplatesSubtitle') }}
            </div>
          </div>
        </template>

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

        <template #footer>
          <n-space justify="end">
            <n-button data-testid="prompt-template-cancel-button" @click="handleCancelPromptTemplateEditing">
              {{ t('common.cancel') }}
            </n-button>
            <n-button type="primary" data-testid="prompt-template-save-button" @click="handleSavePromptTemplate">
              {{ t('common.save') }}
            </n-button>
          </n-space>
        </template>
      </n-modal>

      <div v-if="!isMobile" class="config-table-wrapper prompt-template-table-wrapper">
        <div
          data-testid="prompt-template-table"
          class="prompt-template-table"
          :class="{ 'prompt-template-table--loading': promptTemplatesLoading }"
        >
          <div class="prompt-template-table__header">
            <div>{{ t('config.promptTemplateOrder') }}</div>
            <div>{{ t('config.promptTemplateName') }}</div>
            <div>{{ t('config.promptTemplateContent') }}</div>
            <div>{{ t('config.promptTemplateActive') }}</div>
            <div>{{ t('config.promptTemplateUpdatedAt') }}</div>
            <div>{{ t('config.actions') }}</div>
          </div>
          <n-spin :show="promptTemplatesLoading">
            <div v-if="!promptTemplatesLoading && promptTemplates.length === 0" class="config-empty" data-testid="prompt-template-empty">
              {{ t('config.promptTemplateEmpty') }}
            </div>
            <Draggable
              v-model="promptTemplates"
              item-key="id"
              tag="div"
              handle=".prompt-template-drag-handle"
              ghost-class="prompt-template-sortable--ghost"
              chosen-class="prompt-template-sortable--chosen"
              drag-class="prompt-template-sortable--dragging"
              :animation="160"
              :disabled="isPromptTemplateDragDisabled()"
              @start="handlePromptTemplateDragStart"
              @end="handlePromptTemplateDragEnd"
            >
              <template #item="{ element: template, index }">
                <div class="prompt-template-table__row" :data-testid="`prompt-template-row-${template.id}`">
                  <div class="prompt-template-order-cell">
                    <n-icon
                      class="prompt-template-drag-handle"
                      :component="ReorderThreeOutline"
                      :size="22"
                      :title="t('config.promptTemplateDragToReorder')"
                    />
                    <span class="prompt-template-order-index">{{ index + 1 }}</span>
                  </div>
                  <div class="prompt-template-table__name">{{ template.name }}</div>
                  <div class="prompt-template-content-preview">
                    {{ template.content.substring(0, 100) }}{{ template.content.length > 100 ? '...' : '' }}
                  </div>
                  <div>
                    <n-tag :type="template.is_active ? 'success' : 'default'" round>
                      {{ template.is_active ? t('common.enabled') : t('common.disabled') }}
                    </n-tag>
                  </div>
                  <div class="prompt-template-table__date">{{ new Date(template.updated_at).toLocaleString() }}</div>
                  <n-space size="small">
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
                  </n-space>
                </div>
              </template>
            </Draggable>
          </n-spin>
        </div>
      </div>

      <n-spin v-else :show="promptTemplatesLoading">
        <div v-if="!promptTemplatesLoading && promptTemplates.length === 0" class="config-empty" data-testid="prompt-template-empty">
          {{ t('config.promptTemplateEmpty') }}
        </div>
        <Draggable
          v-model="promptTemplates"
          item-key="id"
          tag="div"
          handle=".prompt-template-drag-handle"
          ghost-class="prompt-template-sortable--ghost"
          chosen-class="prompt-template-sortable--chosen"
          drag-class="prompt-template-sortable--dragging"
          :animation="160"
          :disabled="isPromptTemplateDragDisabled()"
          @start="handlePromptTemplateDragStart"
          @end="handlePromptTemplateDragEnd"
        >
          <template #item="{ element: template }">
            <div class="prompt-template-mobile__item" :data-testid="`prompt-template-card-${template.id}`">
              <div class="prompt-template-mobile__top">
                <div class="prompt-template-mobile__title-group">
                  <n-icon
                    class="prompt-template-drag-handle"
                    :component="ReorderThreeOutline"
                    :size="22"
                    :title="t('config.promptTemplateDragToReorder')"
                  />
                  <div>
                    <div class="prompt-template-mobile__title">{{ template.name }}</div>
                    <div class="prompt-template-mobile__meta">{{ new Date(template.updated_at).toLocaleString() }}</div>
                  </div>
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
          </template>
        </Draggable>
      </n-spin>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref } from 'vue'
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NGi,
  NGrid,
  NIcon,
  NInput,
  NPopconfirm,
  NSpace,
  NSpin,
  NSwitch,
  NTag,
  NModal,
  type FormInst
} from 'naive-ui'
import { useI18n } from 'vue-i18n'
import { useMessage } from 'naive-ui'
import {
  createPromptTemplate,
  deletePromptTemplate,
  getPromptTemplates,
  reorderPromptTemplates,
  updatePromptTemplate,
  type PromptTemplate
} from '../../api'
import VariableEditor from '../../components/VariableEditor.vue'
import { ReorderThreeOutline } from '@vicons/ionicons5'
import Draggable from 'vuedraggable'

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
const promptTemplateReordering = ref(false)
const promptTemplateDragStartSnapshot = ref<PromptTemplate[]>([])
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

function isPromptTemplateDragDisabled() {
  return promptTemplatesLoading.value || promptTemplateReordering.value || promptTemplates.value.length < 2
}

function normalizePromptTemplateOrder(templates: PromptTemplate[]) {
  return templates.map((template, index) => ({ ...template, sort_order: index + 1 }))
}

function isSamePromptTemplateOrder(left: PromptTemplate[], right: PromptTemplate[]) {
  return left.length === right.length && left.every((template, index) => template.id === right[index]?.id)
}

function handlePromptTemplateDragStart() {
  promptTemplateDragStartSnapshot.value = [...promptTemplates.value]
}

async function handlePromptTemplateDragEnd() {
  const previousTemplates = promptTemplateDragStartSnapshot.value
  promptTemplateDragStartSnapshot.value = []

  if (previousTemplates.length === 0 || isSamePromptTemplateOrder(previousTemplates, promptTemplates.value)) {
    return
  }

  await persistPromptTemplateOrder(promptTemplates.value, previousTemplates)
}

async function persistPromptTemplateOrder(
  nextTemplates: PromptTemplate[],
  previousTemplates: PromptTemplate[]
) {
  promptTemplates.value = normalizePromptTemplateOrder(nextTemplates)
  promptTemplateReordering.value = true

  try {
    promptTemplates.value = await reorderPromptTemplates(promptTemplates.value.map(template => template.id))
  } catch (error: any) {
    promptTemplates.value = previousTemplates
    message.error(error?.response?.data?.detail || t('config.reorderPromptTemplatesFailed'))
  } finally {
    promptTemplateReordering.value = false
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
.prompt-template-modal__header {
  display: grid;
}

.prompt-template-table-wrapper {
  margin-top: 0;
  overflow-x: auto;
  overflow-y: hidden;
}

.prompt-template-table {
  min-width: 960px;
  overflow: hidden;
  border: 1px solid rgba(15, 23, 42, 0.08);
  border-radius: 8px;
  background: #fff;
}

.prompt-template-table--loading {
  opacity: 0.7;
}

.prompt-template-table__header,
.prompt-template-table__row {
  display: grid;
  grid-template-columns: 88px minmax(160px, 1fr) minmax(280px, 1.6fr) 100px 180px 160px;
  align-items: center;
}

.prompt-template-table__header {
  min-height: 44px;
  padding: 0 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 250, 252, 0.9);
  font-size: 13px;
  font-weight: 600;
  color: rgba(15, 23, 42, 0.72);
}

.prompt-template-table__row {
  min-height: 56px;
  padding: 8px 12px;
  border-bottom: 1px solid rgba(15, 23, 42, 0.07);
  transition: background-color 0.16s ease, opacity 0.16s ease;
}

.prompt-template-table__row:last-child {
  border-bottom: 0;
}

.prompt-template-table__row:hover {
  background: rgba(248, 250, 252, 0.72);
}

.prompt-template-table__name {
  min-width: 0;
  padding-right: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 500;
  color: #0f172a;
}

.prompt-template-content-preview {
  min-width: 0;
  padding-right: 12px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: rgba(15, 23, 42, 0.7);
}

.prompt-template-table__date {
  padding-right: 12px;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.65);
}

.prompt-template-order-cell {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  min-height: 32px;
  color: rgba(15, 23, 42, 0.68);
}

.prompt-template-drag-handle {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  flex: 0 0 28px;
  cursor: grab;
  line-height: 1;
  color: rgba(15, 23, 42, 0.52);
}

.prompt-template-order-index {
  min-width: 18px;
  font-variant-numeric: tabular-nums;
  font-size: 13px;
  color: rgba(15, 23, 42, 0.58);
}

.prompt-template-sortable--chosen {
  background: rgba(239, 246, 255, 0.92);
}

.prompt-template-sortable--ghost {
  opacity: 0.42;
}

.prompt-template-sortable--dragging {
  cursor: grabbing;
}

.prompt-template-mobile__item {
  margin-bottom: 8px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(248, 250, 252, 0.8);
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.55);
  transition: border-color 0.16s ease, background-color 0.16s ease, opacity 0.16s ease;
}

.prompt-template-mobile__top,
.prompt-template-mobile__actions {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
}

.prompt-template-mobile__title-group {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr);
  align-items: center;
  gap: 8px;
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
