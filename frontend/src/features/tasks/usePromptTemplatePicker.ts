import { computed, ref, watch, type Ref } from 'vue'

import { getPromptTemplates, type PromptTemplate } from '../../api'
import {
  filterPromptTemplatesByTags,
  getActivePromptTemplates,
  getPromptTemplateTags,
} from '../../utils/promptTemplates'

export function usePromptTemplatePicker(prompt: Ref<string>) {
  const showTemplateDrawer = ref(false)
  const promptTemplates = ref<PromptTemplate[]>([])
  const promptTemplatesLoading = ref(false)
  const selectedTemplateTags = ref<string[]>([])
  const templateTagFilterVisible = ref(false)
  const pendingTemplate = ref<PromptTemplate | null>(null)
  const promptVariableTips = ref<Record<string, string> | undefined>(undefined)

  const activePromptTemplates = computed(() =>
    getActivePromptTemplates(promptTemplates.value)
  )
  const templateTagOptions = computed(() =>
    getPromptTemplateTags(activePromptTemplates.value).map(tag => ({
      label: tag,
      value: tag,
    }))
  )
  const filteredPromptTemplates = computed(() =>
    filterPromptTemplatesByTags(
      activePromptTemplates.value,
      selectedTemplateTags.value,
    )
  )

  watch(showTemplateDrawer, (visible) => {
    if (!visible) pendingTemplate.value = null
  })

  async function loadTemplates() {
    promptTemplatesLoading.value = true
    try {
      promptTemplates.value = await getPromptTemplates()
    } catch {
      promptTemplates.value = []
    } finally {
      promptTemplatesLoading.value = false
    }
  }

  function handleTemplateTagFilterUpdate(tags: string[] | null) {
    selectedTemplateTags.value = tags ?? []
    templateTagFilterVisible.value = false
  }

  function applyPromptTemplate(template: PromptTemplate) {
    prompt.value = template.content
    if (template.variable_tips) {
      promptVariableTips.value = template.variable_tips
    }
  }

  function handleTemplateItemClick(template: PromptTemplate) {
    if (!prompt.value.trim()) {
      applyPromptTemplate(template)
      showTemplateDrawer.value = false
      return
    }
    pendingTemplate.value = template
  }

  function confirmTemplateOverwrite() {
    if (!pendingTemplate.value) return
    applyPromptTemplate(pendingTemplate.value)
    pendingTemplate.value = null
    showTemplateDrawer.value = false
  }

  function cancelTemplateOverwrite() {
    pendingTemplate.value = null
  }

  return {
    activePromptTemplates,
    applyPromptTemplate,
    cancelTemplateOverwrite,
    confirmTemplateOverwrite,
    filteredPromptTemplates,
    handleTemplateItemClick,
    handleTemplateTagFilterUpdate,
    loadTemplates,
    pendingTemplate,
    promptTemplates,
    promptTemplatesLoading,
    promptVariableTips,
    selectedTemplateTags,
    showTemplateDrawer,
    templateTagFilterVisible,
    templateTagOptions,
  }
}
