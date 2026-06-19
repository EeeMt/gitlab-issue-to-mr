<template>
  <div class="run-instruction-editor">
    <n-input
      ref="inputRef"
      :value="modelValue"
      type="textarea"
      :autosize="{ minRows: 7, maxRows: 18 }"
      :placeholder="t('runInstruction.templatePlaceholder')"
      @update:value="emit('update:modelValue', $event)"
    />
    <div class="run-instruction-editor__toolbar">
      <details
        v-if="availablePlaceholders.length"
        ref="variablesRef"
        class="run-instruction-editor__variables"
      >
        <summary class="run-instruction-editor__variables-summary" data-testid="variable-picker-toggle">
          <span class="run-instruction-editor__variables-icon" aria-hidden="true">
            <n-icon :component="CodeSlashOutline" size="14" />
          </span>
          <span class="run-instruction-editor__variables-label">
            {{ t('runInstruction.insertVariable') }}
          </span>
          <span class="run-instruction-editor__variables-chevron" aria-hidden="true">›</span>
        </summary>
        <div class="run-instruction-editor__variables-panel">
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
      </details>
      <n-space :size="4">
        <n-button size="tiny" quaternary @click="emit('restore-default')">
          {{ t('runInstruction.restoreDefault') }}
        </n-button>
        <n-button v-if="previewEnabled" size="tiny" quaternary :loading="previewLoading" @click="emit('preview')">
          {{ t('runInstruction.preview') }}
        </n-button>
      </n-space>
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
      v-if="previewResult"
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
          <span>{{ t('runInstruction.previewReady', { count: previewResult.length }) }}</span>
        </span>
        <span class="run-instruction-editor__preview-chevron" aria-hidden="true">›</span>
      </summary>
      <div class="run-instruction-editor__preview-body">
        <pre class="run-instruction-editor__preview">{{ previewResult }}</pre>
      </div>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { NAlert, NButton, NIcon, NInput, NSpace } from 'naive-ui'
import { AddOutline, CodeSlashOutline, DocumentTextOutline } from '@vicons/ionicons5'
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
  preview: []
}>()

const { t } = useI18n()
const inputRef = ref<InstanceType<typeof NInput> | null>(null)
const variablesRef = ref<HTMLDetailsElement | null>(null)
const previewExpanded = ref(false)
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

watch(() => props.previewResult, (value, previousValue) => {
  if (!value) {
    previewExpanded.value = false
  } else if (value !== previousValue) {
    previewExpanded.value = true
  }
}, { immediate: true })

function insertPlaceholder(name: string) {
  const syntax = placeholderSyntax(name)
  const textarea = (inputRef.value?.$el as HTMLElement | undefined)?.querySelector('textarea')
  const start = textarea?.selectionStart ?? props.modelValue.length
  const end = textarea?.selectionEnd ?? start
  emit('update:modelValue', `${props.modelValue.slice(0, start)}${syntax}${props.modelValue.slice(end)}`)
  if (variablesRef.value) variablesRef.value.open = false
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
  previewExpanded.value = (event.currentTarget as HTMLDetailsElement).open
}
</script>

<style scoped>
.run-instruction-editor {
  display: grid;
  gap: 8px;
  width: 100%;
}

.run-instruction-editor__toolbar {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  justify-content: space-between;
  gap: 8px;
}

.run-instruction-editor__variables {
  min-width: 0;
  flex: 1 1 260px;
}

.run-instruction-editor__variables-summary,
.run-instruction-editor__preview-summary {
  display: flex;
  align-items: center;
  list-style: none;
  cursor: pointer;
  user-select: none;
}

.run-instruction-editor__variables-summary::-webkit-details-marker,
.run-instruction-editor__preview-summary::-webkit-details-marker {
  display: none;
}

.run-instruction-editor__variables-summary {
  width: fit-content;
  min-height: 28px;
  padding: 0 8px;
  gap: 6px;
  border: 1px solid var(--n-border-color);
  border-radius: 6px;
  color: var(--n-text-color-2);
  background: transparent;
  font-size: 12px;
  transition: border-color 0.15s ease, color 0.15s ease, background-color 0.15s ease;
}

.run-instruction-editor__variables[open] .run-instruction-editor__variables-summary {
  border-color: var(--n-text-color-3);
  color: var(--n-text-color);
  background: var(--n-action-color);
}

.run-instruction-editor__variables-icon {
  display: inline-flex;
  align-items: center;
  color: var(--n-text-color-3);
}

.run-instruction-editor__variables-label {
  font-weight: 500;
}

.run-instruction-editor__variables-chevron,
.run-instruction-editor__preview-chevron {
  font-size: 18px;
  line-height: 1;
  transform: rotate(0deg);
  transition: transform 0.15s ease;
}

.run-instruction-editor__variables[open] .run-instruction-editor__variables-chevron,
.run-instruction-editor__preview-card[open] .run-instruction-editor__preview-chevron {
  transform: rotate(90deg);
}

.run-instruction-editor__variables-panel {
  width: min(380px, 100%);
  margin-top: 6px;
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 10px;
  background: var(--n-color-modal, var(--n-color));
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.12);
}

.run-instruction-editor__variables-heading {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 10px 12px 8px;
  border-bottom: 1px solid var(--n-divider-color);
}

.run-instruction-editor__variables-heading strong {
  color: var(--n-text-color);
  font-size: 12px;
  line-height: 18px;
}

.run-instruction-editor__variables-heading span {
  color: var(--n-text-color-3);
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
  border-radius: 7px;
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
  color: var(--n-text-color);
  font-family: var(--font-mono, monospace);
  font-size: 13px;
  font-weight: 600;
  line-height: 19px;
  overflow-wrap: anywhere;
}

.run-instruction-editor__variable-copy > span {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.run-instruction-editor__variable-add {
  color: var(--n-text-color-3);
  justify-self: center;
}

.run-instruction-editor__preview-card {
  overflow: hidden;
  border: 1px solid var(--n-border-color);
  border-radius: 9px;
  background: var(--n-color);
}

.run-instruction-editor__preview-card[open] {
  border-color: var(--n-border-color);
  box-shadow: none;
}

.run-instruction-editor__preview-summary {
  gap: 10px;
  min-height: 46px;
  padding: 7px 10px;
}

.run-instruction-editor__preview-card[open] .run-instruction-editor__preview-summary {
  background: var(--n-action-color);
}

.run-instruction-editor__preview-status {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex: 0 0 26px;
  border-radius: 7px;
  color: var(--n-text-color-2);
  background: var(--n-color);
}

.run-instruction-editor__preview-heading {
  display: flex;
  min-width: 0;
  flex: 1;
  flex-direction: column;
  gap: 1px;
}

.run-instruction-editor__preview-heading strong {
  color: var(--n-text-color);
  font-size: 12px;
  line-height: 18px;
}

.run-instruction-editor__preview-heading span {
  color: var(--n-text-color-3);
  font-size: 11px;
  line-height: 16px;
}

.run-instruction-editor__preview-chevron {
  color: var(--n-text-color-3);
}

.run-instruction-editor__preview-body {
  padding: 0 10px 10px;
}

.run-instruction-editor__preview {
  max-height: 320px;
  margin: 0;
  padding: 10px 12px;
  overflow: auto;
  border: 1px solid var(--n-divider-color);
  border-radius: 7px;
  color: var(--n-text-color-2);
  background: var(--n-action-color);
  font-family: var(--font-mono, monospace);
  font-size: 12px;
  line-height: 1.65;
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}

@media (hover: hover) and (pointer: fine) {
  .run-instruction-editor__variables-summary:hover {
    border-color: var(--n-text-color-3);
    color: var(--n-text-color);
    background: var(--n-action-color);
  }

  .run-instruction-editor__variable:hover {
    background: var(--n-action-color);
  }

  .run-instruction-editor__variable:hover .run-instruction-editor__variable-add {
    color: var(--n-text-color);
  }
}

@media (prefers-reduced-motion: reduce) {
  .run-instruction-editor__variables-summary,
  .run-instruction-editor__variables-chevron,
  .run-instruction-editor__preview-chevron {
    transition: none;
  }
}
</style>
