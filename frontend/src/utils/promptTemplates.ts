import type { PromptTemplate } from '../api'

export function getPromptTemplateTags(templates: PromptTemplate[]): string[] {
  const tags = new Set<string>()
  for (const template of templates) {
    for (const tag of template.tags ?? []) {
      tags.add(tag)
    }
  }
  return Array.from(tags).sort((left, right) => left.localeCompare(right))
}

export function getActivePromptTemplates(templates: PromptTemplate[]): PromptTemplate[] {
  return templates.filter(template => template.is_active)
}

export function filterPromptTemplatesByTags(
  templates: PromptTemplate[],
  selectedTags: string[]
): PromptTemplate[] {
  if (selectedTags.length === 0) {
    return templates
  }

  return templates.filter(template => {
    const templateTags = new Set(template.tags ?? [])
    return selectedTags.every(tag => templateTags.has(tag))
  })
}
