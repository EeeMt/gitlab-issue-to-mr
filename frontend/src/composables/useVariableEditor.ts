import { computed, ref, type ComputedRef, type Ref } from 'vue'
import type { VariableTip } from '../types/prompt'

/**
 * Composable for managing prompt variable extraction and tips.
 */
export function useVariableEditor(
  content: Ref<string>,
  templateTips: Ref<Record<string, string> | undefined>
) {
  // Local overrides for tips (user-editable per session)
  const localTips = ref<Record<string, string>>({})

  /**
   * Extract variables from content matching {{variable}} pattern
   */
  function extractVariables(text: string): string[] {
    const matches = text.match(/\{\{([^}]+)\}\}/g)
    if (!matches) return []
    return [...new Set(matches.map(m => m.replace(/\{\{|\}\}/g, '')))]
  }

  // All unique variables detected in content
  const variables = computed(() => extractVariables(content.value))

  // Merge template tips with local overrides (local takes precedence)
  const mergedTips: ComputedRef<Record<string, string>> = computed(() => {
    const merged: Record<string, string> = {}
    // Start with template tips
    if (templateTips.value) {
      for (const [key, value] of Object.entries(templateTips.value)) {
        merged[key] = value
      }
    }
    // Override with local tips
    for (const [key, value] of Object.entries(localTips.value)) {
      merged[key] = value
    }
    return merged
  })

  /**
   * Update tip for a specific variable
   */
  function updateTip(varName: string, tip: string): void {
    localTips.value = {
      ...localTips.value,
      [varName]: tip
    }
  }

  /**
   * Get all variables with their display tips
   */
  const variablesWithTips: ComputedRef<VariableTip[]> = computed(() => {
    return variables.value.map(name => ({
      name,
      tip: mergedTips.value[name] || ''
    }))
  })

  /**
     * Set local tips from template (e.g., when selecting a template)
   */
  function setTemplateTips(tips: Record<string, string> | undefined): void {
    // Clear local overrides that are no longer in template
    const newLocalTips: Record<string, string> = {}
    for (const [key, value] of Object.entries(localTips.value)) {
      if (tips && key in tips) {
        newLocalTips[key] = value
      }
    }
    localTips.value = newLocalTips
  }

  return {
    variables,
    mergedTips,
    updateTip,
    variablesWithTips,
    setTemplateTips
  }
}
