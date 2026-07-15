<template>
  <div
    class="run-instruction-editor"
    :class="{ 'run-instruction-editor--embedded': embedded }"
    :style="editorThemeStyle"
  >
    <div v-if="!hideActions" class="run-instruction-editor__actions">
      <n-button
        v-if="!hidePromptOnly"
        size="tiny"
        quaternary
        @click="emit('use-prompt-only')"
      >
        {{ t('runInstruction.usePromptOnly') }}
      </n-button>
      <n-button size="tiny" quaternary @click="emit('restore-default')">
        {{ t('runInstruction.restoreDefault') }}
      </n-button>
    </div>
    <div v-if="previewEnabled" class="run-instruction-editor__switchbar">
      <div class="run-instruction-editor__tabs" role="tablist">
        <button
          :id="editTabId"
          type="button"
          role="tab"
          class="run-instruction-editor__tab"
          :class="{ 'run-instruction-editor__tab--active': activeView === 'edit' }"
          :aria-selected="activeView === 'edit'"
          :aria-controls="editPanelId"
          data-testid="editor-tab"
          @click="setActiveView('edit')"
        >
          <n-icon :component="CodeSlashOutline" size="14" />
          {{ t('runInstruction.editorTab') }}
        </button>
        <button
          :id="previewTabId"
          type="button"
          role="tab"
          class="run-instruction-editor__tab"
          :class="{ 'run-instruction-editor__tab--active': activeView === 'preview' }"
          :aria-selected="activeView === 'preview'"
          :aria-controls="previewPanelId"
          data-testid="preview-tab"
          @click="setActiveView('preview')"
        >
          <n-icon :component="DocumentTextOutline" size="14" />
          {{ t('runInstruction.previewTab') }}
        </button>
      </div>
      <n-button
        v-if="activeView === 'preview'"
        size="tiny"
        quaternary
        :loading="previewLoading"
        data-testid="preview-refresh"
        @click="emit('preview')"
      >
        <template #icon>
          <n-icon :component="RefreshOutline" size="14" />
        </template>
        {{ t('common.refresh') }}
      </n-button>
    </div>
    <div
      class="run-instruction-editor__stage"
      :class="{ 'run-instruction-editor__stage--switchable': previewEnabled }"
      :style="stageStyle"
    >
      <div
        :id="previewEnabled ? editPanelId : undefined"
        ref="editPanelRef"
        class="run-instruction-editor__view run-instruction-editor__edit-panel"
        :class="{ 'run-instruction-editor__view--active': !previewEnabled || activeView === 'edit' }"
        :role="previewEnabled ? 'tabpanel' : undefined"
        :aria-labelledby="previewEnabled ? editTabId : undefined"
        :aria-hidden="previewEnabled ? activeView !== 'edit' : undefined"
        :inert="previewEnabled && activeView !== 'edit'"
        data-testid="editor-panel"
      >
          <n-input
            ref="inputRef"
            :value="modelValue"
            type="textarea"
            :rows="fixedRows"
            :autosize="fixedRows ? false : { minRows: 7, maxRows: 18 }"
            :resizable="!fixedRows"
            :placeholder="t('runInstruction.templatePlaceholder')"
            @update:value="emit('update:modelValue', $event)"
          />
          <div class="run-instruction-editor__toolbar">
            <n-popover
              v-if="availablePlaceholders.length"
              :show="variablePickerVisible"
              trigger="click"
              placement="bottom-start"
              :show-arrow="false"
              raw
              class="run-instruction-editor__variables"
              @update:show="variablePickerVisible = $event"
            >
              <template #trigger>
                <n-button
                  size="tiny"
                  secondary
                  data-testid="variable-picker-toggle"
                  :aria-expanded="variablePickerVisible"
                  aria-haspopup="menu"
                >
                  <template #icon>
                    <n-icon :component="CodeSlashOutline" size="14" />
                  </template>
                  {{ t('runInstruction.insertVariable') }}
                  <n-icon
                    :component="ChevronDownOutline"
                    size="14"
                    class="run-instruction-editor__variables-chevron"
                    :class="{ 'run-instruction-editor__variables-chevron--open': variablePickerVisible }"
                  />
                </n-button>
              </template>
              <div
                class="run-instruction-editor__variables-panel"
                :style="editorThemeStyle"
                role="menu"
              >
                <div class="run-instruction-editor__variables-heading">
                  <strong>{{ t('runInstruction.availableVariables') }}</strong>
                  <span>{{ t('runInstruction.variableInsertHint') }}</span>
                </div>
                <div class="run-instruction-editor__variables-list">
                  <button
                    v-for="placeholder in availablePlaceholders"
                    :key="placeholder"
                    type="button"
                    class="run-instruction-editor__variable"
                    :data-placeholder="placeholder"
                    role="menuitem"
                    @click="insertPlaceholder(placeholder)"
                  >
                    <span class="run-instruction-editor__variable-copy">
                      <code>{{ placeholderSyntax(placeholder) }}</code>
                      <span>{{ placeholderDescription(placeholder) }}</span>
                    </span>
                    <n-icon
                      :component="AddOutline"
                      size="15"
                      class="run-instruction-editor__variable-add"
                      aria-hidden="true"
                    />
                  </button>
                </div>
              </div>
            </n-popover>
          </div>
      </div>
      <div
        v-if="previewEnabled"
        :id="previewPanelId"
        ref="previewPanelRef"
        class="run-instruction-editor__view run-instruction-editor__preview-panel"
        :class="{ 'run-instruction-editor__view--active': activeView === 'preview' }"
        role="tabpanel"
        :aria-labelledby="previewTabId"
        :aria-hidden="activeView !== 'preview'"
        :inert="activeView !== 'preview'"
        data-testid="preview-panel"
      >
          <div v-if="previewError" class="run-instruction-editor__preview-message">
            <n-alert type="error" :bordered="false">{{ previewError }}</n-alert>
          </div>
          <pre v-if="previewResult" class="run-instruction-editor__preview">{{ previewResult }}</pre>
          <div v-else class="run-instruction-editor__preview-empty">
            <n-icon :component="DocumentTextOutline" size="24" aria-hidden="true" />
            <span>
              {{ previewLoading
                ? t('runInstruction.previewLoading')
                : t('runInstruction.previewEmpty') }}
            </span>
          </div>
      </div>
    </div>
    <n-alert v-if="unknownPlaceholders.length" type="error" :bordered="false">
      {{ t('runInstruction.unknownPlaceholders', { names: unknownPlaceholders.join(', ') }) }}
    </n-alert>
    <n-alert
      v-else-if="warnWhenUserPromptMissing && !usedPlaceholders.includes('user_prompt')"
      type="info"
      :bordered="false"
    >
      {{ t('runInstruction.userPromptMissing') }}
    </n-alert>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { NAlert, NButton, NIcon, NInput, NPopover, useThemeVars } from 'naive-ui'
import {
  AddOutline,
  ChevronDownOutline,
  CodeSlashOutline,
  DocumentTextOutline,
  RefreshOutline
} from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'

const props = withDefaults(defineProps<{
  modelValue: string
  availablePlaceholders: string[]
  knownPlaceholders?: string[]
  previewEnabled?: boolean
  previewLoading?: boolean
  previewResult?: string
  previewError?: string
  warnWhenUserPromptMissing?: boolean
  hideActions?: boolean
  hidePromptOnly?: boolean
  fixedRows?: number
  embedded?: boolean
}>(), {
  previewEnabled: false,
  previewLoading: false,
  previewResult: '',
  previewError: '',
  warnWhenUserPromptMissing: true,
  hideActions: false,
  hidePromptOnly: false,
  fixedRows: undefined,
  embedded: false
})

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'restore-default': []
  'use-prompt-only': []
  preview: []
}>()

const { t } = useI18n()
const themeVars = useThemeVars()
const inputRef = ref<InstanceType<typeof NInput> | null>(null)
const editPanelRef = ref<HTMLElement | null>(null)
const previewPanelRef = ref<HTMLElement | null>(null)
const stageHeight = ref<number | null>(null)
const variablePickerVisible = ref(false)
const activeView = ref<'edit' | 'preview'>('edit')
const editorId = useId()
const editTabId = `${editorId}-edit-tab`
const previewTabId = `${editorId}-preview-tab`
const editPanelId = `${editorId}-edit-panel`
const previewPanelId = `${editorId}-preview-panel`
const stageStyle = computed(() => (
  props.previewEnabled && stageHeight.value !== null
    ? { height: `${stageHeight.value}px` }
    : undefined
))
const editorThemeStyle = computed(() => ({
  '--rie-surface': themeVars.value.cardColor,
  '--rie-popover': themeVars.value.popoverColor,
  '--rie-subtle': themeVars.value.actionColor,
  '--rie-hover': themeVars.value.hoverColor,
  '--rie-code': themeVars.value.codeColor,
  '--rie-border': themeVars.value.borderColor,
  '--rie-divider': themeVars.value.dividerColor,
  '--rie-text-1': themeVars.value.textColor1,
  '--rie-text-2': themeVars.value.textColor2,
  '--rie-text-3': themeVars.value.textColor3,
  '--rie-primary': themeVars.value.primaryColor,
  '--rie-shadow': themeVars.value.boxShadow2,
  '--rie-font-mono': themeVars.value.fontFamilyMono
}))
const describedPlaceholders = new Set([
  'user_prompt',
  'issue_title',
  'project_path',
  'branch_name',
  'base_branch',
  'target_branch',
  'task_mode',
  'require_changes',
  'previous_task_summaries_path',
  'ci_failure_context_path'
])
const usedPlaceholders = computed(() => {
  const seen = new Set<string>()
  for (const match of props.modelValue.matchAll(/\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}/g)) {
    seen.add(match[1])
  }
  return [...seen]
})
const unknownPlaceholders = computed(() =>
  usedPlaceholders.value.filter(
    (name) => !(props.knownPlaceholders ?? props.availablePlaceholders).includes(name)
  )
)
let panelResizeObserver: ResizeObserver | null = null

function activePanelElement() {
  return activeView.value === 'preview' ? previewPanelRef.value : editPanelRef.value
}

function measureActivePanel() {
  if (!props.previewEnabled) {
    stageHeight.value = null
    return
  }
  const height = activePanelElement()?.getBoundingClientRect().height ?? 0
  if (height > 0) {
    stageHeight.value = Math.ceil(height)
  }
}

function observePanels() {
  panelResizeObserver?.disconnect()
  if (!panelResizeObserver) return
  if (editPanelRef.value) panelResizeObserver.observe(editPanelRef.value)
  if (previewPanelRef.value) panelResizeObserver.observe(previewPanelRef.value)
}

watch(activeView, async () => {
  await nextTick()
  measureActivePanel()
})

watch(() => props.previewEnabled, async () => {
  await nextTick()
  observePanels()
  measureActivePanel()
})

onMounted(async () => {
  await nextTick()
  measureActivePanel()
  if (typeof ResizeObserver !== 'undefined') {
    panelResizeObserver = new ResizeObserver((entries) => {
      if (entries.some((entry) => entry.target === activePanelElement())) {
        measureActivePanel()
      }
    })
    observePanels()
  }
})

onBeforeUnmount(() => {
  panelResizeObserver?.disconnect()
})

function insertPlaceholder(name: string) {
  const syntax = placeholderSyntax(name)
  const textarea = (inputRef.value?.$el as HTMLElement | undefined)?.querySelector('textarea')
  const start = textarea?.selectionStart ?? props.modelValue.length
  const end = textarea?.selectionEnd ?? start
  emit('update:modelValue', `${props.modelValue.slice(0, start)}${syntax}${props.modelValue.slice(end)}`)
  variablePickerVisible.value = false
  void nextTick(() => {
    textarea?.focus()
    textarea?.setSelectionRange(start + syntax.length, start + syntax.length)
  })
}

function placeholderSyntax(name: string) {
  return `{{${name}}}`
}

function placeholderDescription(name: string) {
  if (describedPlaceholders.has(name)) {
    return t(`runInstruction.placeholderDescriptions.${name}`)
  }
  return t('runInstruction.placeholderDescriptionFallback')
}

function setActiveView(view: 'edit' | 'preview') {
  activeView.value = view
  variablePickerVisible.value = false
  if (view === 'preview' && !props.previewResult && !props.previewLoading) {
    emit('preview')
  }
}
</script>

<style scoped>
.run-instruction-editor {
  display: grid;
  gap: 8px;
  width: 100%;
}

.run-instruction-editor :deep(textarea) {
  font-size: 12px;
  line-height: 1.65;
  transition: height 0.25s ease;
}

.run-instruction-editor__actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.run-instruction-editor__switchbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  min-height: 30px;
  gap: 8px;
}

.run-instruction-editor__tabs {
  display: inline-flex;
  align-items: center;
  gap: 2px;
  padding: 2px;
  border-radius: 7px;
  background: var(--rie-subtle);
}

.run-instruction-editor__tab {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 5px;
  min-width: 72px;
  height: 26px;
  padding: 0 10px;
  border: 0;
  border-radius: 5px;
  color: var(--rie-text-3);
  background: transparent;
  font: inherit;
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.run-instruction-editor__tab--active {
  color: var(--rie-text-1);
  background: var(--rie-surface);
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.08);
}

.run-instruction-editor__stage--switchable {
  position: relative;
  overflow: hidden;
  border: 1px solid var(--rie-border);
  border-radius: 8px;
  background: var(--rie-surface);
  transition: height 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.run-instruction-editor__edit-panel {
  display: grid;
  gap: 8px;
}

.run-instruction-editor__stage--switchable .run-instruction-editor__edit-panel {
  padding: 8px;
}

.run-instruction-editor--embedded .run-instruction-editor__stage--switchable {
  border: 0;
  border-radius: 0;
  background: transparent;
}

.run-instruction-editor--embedded .run-instruction-editor__stage--switchable .run-instruction-editor__edit-panel {
  padding: 0;
}

.run-instruction-editor__view {
  width: 100%;
  opacity: 0;
  pointer-events: none;
  transform: translateY(2px);
  transition: opacity 0.16s ease, transform 0.18s cubic-bezier(0.4, 0, 0.2, 1);
}

.run-instruction-editor__view:not(.run-instruction-editor__view--active) {
  position: absolute;
  top: 0;
  left: 0;
}

.run-instruction-editor__view--active {
  position: relative;
  z-index: 1;
  opacity: 1;
  pointer-events: auto;
  transform: translateY(0);
}

.run-instruction-editor__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
}

.run-instruction-editor__variables {
  display: inline-flex;
}

.run-instruction-editor__variables-chevron {
  transition: transform 0.15s ease;
}

.run-instruction-editor__variables-chevron--open {
  transform: rotate(180deg);
}

.run-instruction-editor__variables-panel {
  width: min(360px, calc(100vw - 32px));
  overflow: hidden;
  border: 1px solid var(--rie-border);
  border-radius: 8px;
  background: var(--rie-popover);
  box-shadow: var(--rie-shadow);
}

.run-instruction-editor__variables-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--rie-divider);
}

.run-instruction-editor__variables-heading strong {
  color: var(--rie-text-1);
  font-size: 12px;
  line-height: 18px;
}

.run-instruction-editor__variables-heading span {
  color: var(--rie-text-3);
  font-size: 11px;
  line-height: 16px;
}

.run-instruction-editor__variables-list {
  display: grid;
  max-height: 286px;
  padding: 6px;
  overflow-y: auto;
  overscroll-behavior: contain;
  scrollbar-width: thin;
}

.run-instruction-editor__variable {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 24px;
  align-items: center;
  gap: 12px;
  width: 100%;
  padding: 9px 10px;
  border: 0;
  border-radius: 5px;
  color: inherit;
  background: transparent;
  text-align: left;
  cursor: pointer;
}

.run-instruction-editor__variable-copy {
  display: flex;
  min-width: 0;
  flex-direction: column;
  gap: 2px;
}

.run-instruction-editor__variable-copy code {
  color: var(--rie-text-1);
  font-family: var(--rie-font-mono);
  font-size: 13px;
  font-weight: 600;
  line-height: 19px;
  overflow-wrap: anywhere;
}

.run-instruction-editor__variable-copy > span {
  color: var(--rie-text-3);
  font-size: 11px;
  line-height: 16px;
}

.run-instruction-editor__variable-add {
  color: var(--rie-text-3);
  justify-self: center;
}

.run-instruction-editor__preview-panel {
  position: relative;
  min-height: 201px;
  max-height: 420px;
  overflow: auto;
  background: var(--rie-subtle);
}

.run-instruction-editor__preview {
  margin: 0;
  padding: 14px 16px;
  color: var(--rie-text-2);
  background: transparent;
  font-family: var(--rie-font-mono);
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

.run-instruction-editor__preview-message {
  padding: 10px 10px 0;
}

.run-instruction-editor__preview-message :deep(.n-alert-body__content) {
  font-size: 12px;
  line-height: 18px;
}

.run-instruction-editor__preview-empty {
  display: flex;
  min-height: 201px;
  align-items: center;
  justify-content: center;
  flex-direction: column;
  gap: 8px;
  padding: 24px;
  color: var(--rie-text-3);
  font-size: 12px;
  text-align: center;
}

@media (hover: hover) and (pointer: fine) {
  .run-instruction-editor__tab:not(.run-instruction-editor__tab--active):hover {
    color: var(--rie-text-2);
    background: var(--rie-hover);
  }

  .run-instruction-editor__variable:hover {
    background: var(--rie-hover);
  }

  .run-instruction-editor__variable:hover .run-instruction-editor__variable-add {
    color: var(--rie-primary);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-instruction-editor__stage--switchable,
  .run-instruction-editor__view,
  .run-instruction-editor__variables-chevron,
  .run-instruction-editor__view--active {
    transition: none;
  }
}
</style>
