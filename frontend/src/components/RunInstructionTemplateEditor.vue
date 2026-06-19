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
      <div class="run-instruction-editor__placeholders">
        <n-button
          v-for="placeholder in availablePlaceholders"
          :key="placeholder"
          size="tiny"
          quaternary
          class="run-instruction-editor__chip"
          @click="insertPlaceholder(placeholder)"
        >
          {{ placeholderSyntax(placeholder) }}
        </n-button>
      </div>
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
    <details v-if="previewResult">
      <summary>{{ t('runInstruction.preview') }}</summary>
        <pre class="run-instruction-editor__preview">{{ previewResult }}</pre>
    </details>
  </div>
</template>

<script setup lang="ts">
import { computed, nextTick, ref } from 'vue'
import { NAlert, NButton, NInput, NSpace } from 'naive-ui'
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
  void nextTick(() => {
    textarea?.focus()
    textarea?.setSelectionRange(start + syntax.length, start + syntax.length)
  })
}

function placeholderSyntax(name: string) {
  return `{{${name}}}`
}
</script>

<style scoped>
.run-instruction-editor { display: grid; gap: 8px; width: 100%; }
.run-instruction-editor__toolbar { display: flex; justify-content: space-between; gap: 8px; align-items: flex-start; }
.run-instruction-editor__placeholders { display: flex; flex-wrap: wrap; gap: 2px; }
.run-instruction-editor__chip { font-family: var(--font-mono, monospace); }
.run-instruction-editor__preview { margin: 0; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 12px; }
</style>
