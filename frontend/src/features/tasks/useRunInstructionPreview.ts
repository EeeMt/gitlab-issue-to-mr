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
      const taskMode = options.taskMode.value
      const request = {
        issue_id: options.issueId.value ?? options.task.value!.issue_id,
        task_mode: taskMode,
        user_prompt: options.prompt.value.trim() || options.issueDescription.value || '',
        require_changes: taskMode === 'execute' ? options.requireChanges.value : false,
        ...(taskMode === 'freeform'
          ? {}
          : { run_instruction_template: options.runInstructionTemplate.value }),
      }
      const result = await previewRunInstructionTemplate(request)
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
