<template>
  <div class="variable-editor">
    <div ref="editorContainer" class="variable-editor__codemirror" />
    <div v-if="variables.length > 0" class="variable-editor__tips-panel">
      <div class="variable-tips-header">
        <n-icon :component="InformationCircleOutline" size="16" />
        <span>{{ t('createTask.variableTips') }}</span>
      </div>
      <div class="variable-tips-list">
        <div v-for="v in variablesWithTips" :key="v.name" class="variable-tip-item">
          <code class="variable-tip-item__name">{{ v.name }}</code>
          <n-input
            v-if="editable"
            :value="v.tip"
            size="small"
            :placeholder="t('createTask.noTipAvailable')"
            @update:value="(tip) => handleTipChange(v.name, tip)"
          />
          <span v-else class="variable-tip-item__tip">{{ v.tip || t('createTask.noTipAvailable') }}</span>
        </div>
      </div>
    </div>
    <div v-else-if="content && !hasVariables" class="variable-editor__no-variables">
      {{ t('createTask.noVariables') }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { NIcon, NInput } from 'naive-ui'
import { InformationCircleOutline } from '@vicons/ionicons5'
import { EditorView, basicSetup } from 'codemirror'
import { EditorState } from '@codemirror/state'
import { Decoration, DecorationSet, ViewPlugin, ViewUpdate, hoverTooltip } from '@codemirror/view'
import { RangeSetBuilder } from '@codemirror/state'
import { useVariableEditor } from '../composables/useVariableEditor'

const { t } = useI18n()

const props = defineProps<{
  modelValue: string
  variableTips?: Record<string, string>
  editable?: boolean
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:variableTips': [tips: Record<string, string>]
}>()

const editorContainer = ref<HTMLElement | null>(null)
let editorView: EditorView | null = null

const content = computed({
  get: () => props.modelValue,
  set: (value: string) => emit('update:modelValue', value)
})

const templateTips = computed(() => props.variableTips)
const hasVariables = computed(() => content.value.includes('{{') && content.value.includes('}}'))

// Use composable logic inline since we need reactive access
const variablesRef = ref(content.value)
const tipsRef = ref(templateTips.value)
const { variables, mergedTips, updateTip, variablesWithTips } = useVariableEditor(variablesRef, tipsRef)

// Keep reactive refs in sync
watch(content, (val) => {
  variablesRef.value = val
})
watch(templateTips, (val) => {
  tipsRef.value = val
})

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

const lastSyncedTips = ref<Record<string, string>>({ ...(props.variableTips ?? {}) })

watch(
  () => props.variableTips,
  (newTips) => {
    lastSyncedTips.value = { ...(newTips ?? {}) }
  },
  { deep: true, immediate: true }
)

function syncVariableTips(nextTips: Record<string, string>) {
  if (areTipsEqual(nextTips, lastSyncedTips.value)) {
    return
  }

  const clonedTips = { ...nextTips }
  lastSyncedTips.value = clonedTips
  emit('update:variableTips', clonedTips)
}

// Only emit when merged tips actually diverge from the parent prop.
// This avoids re-emitting equivalent objects on every keystroke.
watch(mergedTips, (newTips) => {
  if (props.editable && newTips) {
    syncVariableTips(newTips)
  }
}, { flush: 'post', deep: true })

// Whether tips are editable
const editable = computed(() => props.editable ?? false)

// Handle tip change when editable - use mergedTips which is already cleaned
function handleTipChange(varName: string, tip: string) {
  updateTip(varName, tip)
  const newTips = { ...mergedTips.value, [varName]: tip }
  syncVariableTips(newTips)
}

// Variable pattern decoration - use inclusive: false to not interfere with selection
const variableMark = Decoration.mark({
  class: 'cm-variable-highlight',
  inclusive: false
})

// Create a view plugin that highlights variables
const variableHighlightPlugin = ViewPlugin.fromClass(class {
  decorations: DecorationSet

  constructor(view: EditorView) {
    this.decorations = this.buildDecorations(view)
  }

  update(update: ViewUpdate) {
    // Always rebuild decorations on any update to ensure sync
    if (update.docChanged || update.viewportChanged || update.geometryChanged) {
      this.decorations = this.buildDecorations(update.view)
    }
  }

  buildDecorations(view: EditorView): DecorationSet {
    const builder = new RangeSetBuilder<Decoration>()
    const doc = view.state.doc.toString()
    const regex = /\{\{([^}]+)\}\}/g
    let match

    while ((match = regex.exec(doc)) !== null) {
      const from = match.index
      const to = from + match[0].length
      builder.add(from, to, variableMark)
    }

    return builder.finish()
  }
}, {
  decorations: v => v.decorations
})

// Tooltip for hovering over variables
function createTooltip(view: EditorView, pos: number) {
  const docLength = view.state.doc.length
  if (docLength === 0) {
    return null
  }

  const safePos = Math.min(Math.max(pos, 0), docLength)
  const line = view.state.doc.lineAt(safePos)
  const lineText = line.text
  const lineStart = line.from

  // Find if we're near a {{...}} pattern
  const regex = /\{\{([^}]+)\}\}/g
  let match

  while ((match = regex.exec(lineText)) !== null) {
    const matchStart = lineStart + match.index
    const matchEnd = matchStart + match[0].length

    if (safePos >= matchStart && safePos <= matchEnd && matchStart >= 0 && matchEnd <= docLength) {
      const varName = match[1]
      const tip = mergedTips.value[varName] || ''

      return {
        pos: matchStart,
        end: matchEnd,
        above: true,
        create: () => {
          const dom = document.createElement('div')
          dom.className = 'variable-tooltip'
          dom.innerHTML = `
            <div class="variable-tooltip__name">{{${varName}}}</div>
            <div class="variable-tooltip__tip">${tip || 'No description'}</div>
          `
          return { dom }
        }
      }
    }
  }

  return null
}

const variableTooltip = hoverTooltip((view, pos) => createTooltip(view, pos), {
  hoverTime: 300
})

function createEditor() {
  if (!editorContainer.value) return

  const startState = EditorState.create({
    doc: content.value,
    extensions: [
      basicSetup,
      variableHighlightPlugin,
      variableTooltip,
      EditorView.updateListener.of((update) => {
        if (update.docChanged) {
          const newContent = update.state.doc.toString()
          content.value = newContent
        }
      }),
      EditorView.theme({
        '&': {
          fontSize: '14px',
          maxHeight: '200px',
          width: '100%',
          display: 'block'
        },
        '.cm-scroller': {
          fontFamily: 'monospace',
          overflow: 'auto'
        },
        '.cm-content': {
          padding: '8px 0'
        },
        '.cm-line': {
          padding: '0 12px'
        }
      })
    ]
  })

  editorView = new EditorView({
    state: startState,
    parent: editorContainer.value
  })
}

onMounted(() => {
  createEditor()
})

onBeforeUnmount(() => {
  if (editorView) {
    editorView.destroy()
    editorView = null
  }
})

// Watch for external content changes
watch(() => props.modelValue, (newVal) => {
  if (editorView && newVal !== editorView.state.doc.toString()) {
    editorView.dispatch({
      changes: {
        from: 0,
        to: editorView.state.doc.length,
        insert: newVal
      }
    })
  }
})
</script>

<style scoped>
.variable-editor {
  border: 1px solid rgba(0, 0, 0, 0.12);
  border-radius: 6px;
  overflow: hidden;
  width: 100%;
}

.variable-editor__codemirror {
  background: #fff;
  width: 100%;
  display: block;
}

.variable-editor__codemirror :deep(.cm-editor) {
  min-height: 120px;
  width: 100%;
  display: block;
}

.variable-editor__codemirror :deep(.cm-scroller) {
  overflow-x: auto;
}

.variable-editor__tips-panel {
  border-top: 1px solid rgba(0, 0, 0, 0.08);
  padding: 12px;
  background: rgba(245, 158, 11, 0.04);
}

.variable-tips-header {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  font-weight: 500;
  color: rgba(15, 23, 42, 0.62);
  margin-bottom: 8px;
}

.variable-tips-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.variable-tip-item {
  display: flex;
  align-items: center;
  gap: 8px;
}

.variable-tip-item__name {
  font-family: monospace;
  background: rgba(245, 158, 11, 0.1);
  color: #92400e;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 12px;
  min-width: 80px;
}

.variable-tip-item__tip {
  font-size: 13px;
  color: rgba(15, 23, 42, 0.7);
}

.variable-editor__no-variables {
  padding: 8px 12px;
  font-size: 12px;
  color: rgba(15, 23, 42, 0.4);
  background: rgba(0, 0, 0, 0.02);
  border-top: 1px solid rgba(0, 0, 0, 0.08);
}

/* Global styles for CodeMirror variable highlighting */
:deep(.cm-variable-highlight) {
  background-color: #fef3c7 !important;
  color: #92400e !important;
  padding: 1px 2px;
  border-radius: 3px;
}

/* When highlighted text is selected, keep the highlight background */
:deep(.cm-selectionBackground),
:deep(::selection) {
  background-color: #fef3c7 !important;
}

/* Tooltip styling */
:deep(.variable-tooltip) {
  padding: 8px 12px;
  background: rgba(15, 23, 42, 0.9);
  color: #fff;
  border-radius: 6px;
  font-size: 13px;
  max-width: 300px;
}

:deep(.variable-tooltip__name) {
  font-family: monospace;
  font-weight: 600;
  margin-bottom: 4px;
  color: #fbbf24;
}

:deep(.variable-tooltip__tip) {
  color: rgba(255, 255, 255, 0.85);
  line-height: 1.4;
}
</style>
