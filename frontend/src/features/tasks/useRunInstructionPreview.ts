import { ref, type Ref } from 'vue'

import { previewRunInstructionTemplate, type Task } from '../../api'
import type { TaskMode } from './taskFormModel'

interface RunInstructionPreviewOptions {
  issueId: Readonly<Ref<number | undefined>>
  task: Readonly<Ref<Task | undefined>>
  taskMode: Ref<TaskMode | null>
  prompt: Ref<string>
  issueDescription: Readonly<Ref<string | undefined>>
  runInstructionTemplate: Ref<string>
  requireChanges: Ref<boolean>
}

export function useRunInstructionPreview(options: RunInstructionPreviewOptions) {
  const previewLoading = ref(false)
  const previewResult = ref('')
  const previewError = ref('')
  let requestGeneration = 0

  function invalidateRunInstructionPreview() {
    requestGeneration += 1
    previewLoading.value = false
    previewResult.value = ''
    previewError.value = ''
  }

  async function handleRunInstructionPreview() {
    if (!options.issueId.value && !options.task.value) return
    if (!options.taskMode.value) return

    const generation = ++requestGeneration
    previewLoading.value = true
    previewError.value = ''
    try {
      const result = await previewRunInstructionTemplate({
        issue_id: options.issueId.value ?? options.task.value!.issue_id,
        task_mode: options.taskMode.value,
        user_prompt: options.prompt.value.trim() || options.issueDescription.value || '',
        run_instruction_template: options.runInstructionTemplate.value,
        require_changes: options.taskMode.value === 'plan'
          ? false
          : options.requireChanges.value,
      })
      if (generation !== requestGeneration) return
      previewResult.value = result.rendered_prompt
    } catch (error: unknown) {
      if (generation !== requestGeneration) return
      const apiError = error as {
        response?: { data?: { detail?: string } }
        apiError?: { detail?: string }
      }
      previewError.value = apiError.response?.data?.detail
        || apiError.apiError?.detail
        || String(error)
    } finally {
      if (generation === requestGeneration) previewLoading.value = false
    }
  }

  return {
    handleRunInstructionPreview,
    invalidateRunInstructionPreview,
    previewError,
    previewLoading,
    previewResult,
  }
}
