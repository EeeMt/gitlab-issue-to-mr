import { computed, ref, watch, type ComputedRef, type Ref } from 'vue'
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
   * Handles edge cases:
   * - Empty variable names ({{}}) are ignored
   * - Whitespace-only variable names are trimmed
   * - Duplicates are removed
   */
  function extractVariables(text: string): string[] {
    const matches = text.match(/\{\{([^}]+)\}\}/g)
    if (!matches) return []
    const vars = matches
      .map(m => m.replace(/\{\{|\}\}/g, '').trim())  // Extract and trim
      .filter(v => v.length > 0)  // Remove empty/whitespace-only names
    return [...new Set(vars)]
  }

  // All unique variables detected in content
  const variables = computed(() => extractVariables(content.value))

  // Current variable names as a Set for fast lookup
  const variableSet = computed(() => new Set(variables.value))

  /**
   * Migrate tips when variables are renamed
   * Compare old variables (previous state) against new variables (current state)
   */
  function migrateTipsOnRename(oldVars: Set<string>, newVars: Set<string>): Record<string, string> {
    const migrated: Record<string, string> = {}

    // Find removed variables (in old but not in new)
    const removed = new Set([...oldVars].filter(v => !newVars.has(v)))
    // Find added variables (in new but not in old)
    const added = new Set([...newVars].filter(v => !oldVars.has(v)))

    // Rename detection: if exactly one removed and one added, assume rename
    if (removed.size === 1 && added.size === 1) {
      const oldVar = [...removed][0]
      const newVar = [...added][0]
      // Migrate tip from old variable to new variable
      const oldTip = localTips.value[oldVar] || templateTips.value?.[oldVar]
      if (oldTip) {
        migrated[newVar] = oldTip
      }
    }

    return migrated
  }

  // Watch for variable changes to detect renames and migrate tips
  watch(variableSet, (newVars, oldVars) => {
    if (!oldVars) {
      return
    }

    // Check if there was a rename by comparing old vs new
    const migrations = migrateTipsOnRename(oldVars, newVars)

    if (Object.keys(migrations).length > 0) {
      // Apply migrations to localTips
      const newLocalTips: Record<string, string> = {}
      for (const [key, value] of Object.entries(localTips.value)) {
        // Skip tips for variables that no longer exist in newVars
        if (newVars.has(key)) {
          newLocalTips[key] = value
        }
      }
      // Add migrated tips
      for (const [newVar, tip] of Object.entries(migrations)) {
        newLocalTips[newVar] = tip
      }
      localTips.value = newLocalTips
    }
  }, { flush: 'post' })

  // Merge template tips with local overrides (local takes precedence)
  // But ONLY include tips for variables that exist in content (auto-clean orphan tips)
  const mergedTips: ComputedRef<Record<string, string>> = computed(() => {
    const merged: Record<string, string> = {}
    const vars = variableSet.value

    // Start with template tips, but only include tips for current variables
    if (templateTips.value) {
      for (const [key, value] of Object.entries(templateTips.value)) {
        if (vars.has(key)) {
          merged[key] = value
        }
      }
    }
    // Override with local tips, but only include tips for current variables
    for (const [key, value] of Object.entries(localTips.value)) {
      if (vars.has(key)) {
        merged[key] = value
      }
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
