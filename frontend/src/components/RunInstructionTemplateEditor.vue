<template>
  <div class="run-instruction-editor" :style="editorThemeStyle">
    <n-input
      ref="inputRef"
      :value="modelValue"
      type="textarea"
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
      <div class="run-instruction-editor__actions">
        <n-button size="tiny" quaternary @click="emit('use-prompt-only')">
          {{ t('runInstruction.usePromptOnly') }}
        </n-button>
        <n-button size="tiny" quaternary @click="emit('restore-default')">
          {{ t('runInstruction.restoreDefault') }}
        </n-button>
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
    <n-alert v-if="previewError" type="error" :bordered="false">{{ previewError }}</n-alert>
    <details
      v-if="previewEnabled || previewResult"
      class="run-instruction-editor__preview-card"
      :open="previewExpanded"
      @toggle="handlePreviewToggle"
    >
      <summary class="run-instruction-editor__preview-summary" data-testid="preview-toggle">
        <span class="run-instruction-editor__preview-status" aria-hidden="true">
          <n-icon :component="DocumentTextOutline" size="15" />
        </span>
        <span class="run-instruction-editor__preview-heading">
          <strong>{{ t('runInstruction.preview') }}</strong>
        </span>
        <n-button
          v-if="previewExpanded"
          size="tiny"
          quaternary
          :loading="previewLoading"
          data-testid="preview-refresh"
          @click.stop.prevent="emit('preview')"
        >
          <template #icon>
            <n-icon :component="RefreshOutline" size="14" />
          </template>
          {{ t('common.refresh') }}
        </n-button>
        <span class="run-instruction-editor__preview-chevron" aria-hidden="true">›</span>
      </summary>
      <div v-if="previewResult" class="run-instruction-editor__preview-body">
        <pre class="run-instruction-editor__preview">{{ previewResult }}</pre>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
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
}>(), {
  previewEnabled: false,
  previewLoading: false,
  previewResult: '',
  previewError: '',
  warnWhenUserPromptMissing: true
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
const variablePickerVisible = ref(false)
const previewExpanded = ref(false)

const autosizeMinRows = 7
const autosizeMaxRows = 18
let autosizeRowHeight = 20

function getTextarea(): HTMLTextAreaElement | null {
  return (inputRef.value?.$el as HTMLElement | undefined)?.querySelector('textarea') ?? null
}

function autosizeTextarea() {
  const textarea = getTextarea()
  if (!textarea) return
  const lineHeight = autosizeRowHeight
  const padding = parseFloat(getComputedStyle(textarea).paddingTop) + parseFloat(getComputedStyle(textarea).paddingBottom)
  const minHeight = lineHeight * autosizeMinRows + padding
  const maxHeight = lineHeight * autosizeMaxRows + padding
  textarea.style.height = '0px'
  const scrollHeight = textarea.scrollHeight
  textarea.style.height = `${Math.max(minHeight, Math.min(scrollHeight, maxHeight))}px`
}

onMounted(() => {
  const textarea = getTextarea()
  if (textarea) {
    const computed = getComputedStyle(textarea)
    autosizeRowHeight = parseFloat(computed.lineHeight) || 20
    autosizeTextarea()
  }
})

watch(() => props.modelValue, () => {
  void nextTick(autosizeTextarea)
})
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

function handlePreviewToggle(event: Event) {
  const open = (event.currentTarget as HTMLDetailsElement).open
  previewExpanded.value = open
  if (open && !props.previewResult && !props.previewLoading) {
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
  resize: none;
  overflow-y: auto;
  transition: height 0.25s ease;
}

.run-instruction-editor__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.run-instruction-editor__actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.run-instruction-editor__variables {
  display: inline-flex;
}

.run-instruction-editor__preview-chevron {
  font-size: 18px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.15s ease;
}

.run-instruction-editor__preview-card[open] .run-instruction-editor__preview-chevron {
  transform: rotate(90deg);
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

.run-instruction-editor__preview-card {
  overflow: hidden;
  border: 1px solid var(--rie-border);
  border-radius: 8px;
  background: var(--rie-surface);
}

.run-instruction-editor__preview-card[open] {
  border-color: var(--rie-border);
  box-shadow: none;
}

.run-instruction-editor__preview-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  min-height: 40px;
  padding: 6px 10px;
  list-style: none;
  cursor: pointer;
  user-select: none;
}

.run-instruction-editor__preview-summary::-webkit-details-marker {
  display: none;
}

.run-instruction-editor__preview-card[open] .run-instruction-editor__preview-summary {
  border-bottom: 1px solid var(--rie-divider);
}

.run-instruction-editor__preview-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex: 0 0 20px;
  color: var(--rie-text-2);
}

.run-instruction-editor__preview-heading {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.run-instruction-editor__preview-heading strong {
  color: var(--rie-text-1);
  font-size: 12px;
  line-height: 18px;
}

.run-instruction-editor__preview-chevron {
  color: var(--rie-text-3);
}

.run-instruction-editor__preview-body {
  padding: 8px;
}

.run-instruction-editor__preview {
  max-height: 320px;
  margin: 0;
  padding: 12px;
  overflow: auto;
  border: 0;
  border-radius: 6px;
  color: var(--rie-text-2);
  background: var(--rie-subtle);
  font-family: var(--rie-font-mono);
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

@media (hover: hover) and (pointer: fine) {
  .run-instruction-editor__variable:hover {
    background: var(--rie-hover);
  }

  .run-instruction-editor__variable:hover .run-instruction-editor__variable-add {
    color: var(--rie-primary);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-instruction-editor__variables-chevron,
  .run-instruction-editor__preview-chevron {
    transition: none;
  }
}
</style>
