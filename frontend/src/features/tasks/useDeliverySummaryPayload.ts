import { computed, ref, watch, type Ref } from 'vue'

import { getTaskPayload, type TaskLog } from '../../api'
import { parseTextEntry } from '../../components/task-process/taskProcessUtils'

interface DeliverySummaryPayloadOptions {
  taskId: Readonly<Ref<number>>
  deliverySummaryLog: Readonly<Ref<TaskLog | null | undefined>>
  lastAssistantLog: Readonly<Ref<TaskLog | null | undefined>>
}

export function useDeliverySummaryPayload(options: DeliverySummaryPayloadOptions) {
  const summaryPayloadText = ref('')
  const summaryPayloadLoading = ref(false)
  const summaryPayloadLoaded = ref(false)
  let payloadGeneration = 0

  const selectedSummaryLog = computed(() =>
    options.deliverySummaryLog.value ?? options.lastAssistantLog.value ?? null
  )
  const summaryEntry = computed(() =>
    selectedSummaryLog.value ? parseTextEntry(selectedSummaryLog.value.metadata) : null
  )
  const summaryText = computed(() =>
    summaryPayloadLoaded.value ? summaryPayloadText.value : (summaryEntry.value?.text ?? '')
  )
  const summaryPreview = computed(() => {
    const entry = summaryEntry.value
    if (!entry) return ''
    if (entry.preview) return entry.truncated ? `${entry.preview}…` : entry.preview
    return entry.text.slice(0, 120) || ''
  })

  function resetSummaryPayload() {
    payloadGeneration += 1
    summaryPayloadText.value = ''
    summaryPayloadLoading.value = false
    summaryPayloadLoaded.value = false
  }

  async function loadSummaryPayloadIfNeeded() {
    const entry = summaryEntry.value
    if (!entry) return false
    if (entry.text || summaryPayloadLoaded.value) return true
    if (!entry.payloadId || summaryPayloadLoading.value) return false

    const generation = payloadGeneration
    summaryPayloadLoading.value = true
    try {
      const payload = await getTaskPayload(options.taskId.value, entry.payloadId)
      if (generation !== payloadGeneration) return false
      summaryPayloadText.value = payload.content
      summaryPayloadLoaded.value = true
      return true
    } catch {
      // The caller renders the existing empty state when a payload cannot be loaded.
      return false
    } finally {
      if (generation === payloadGeneration) summaryPayloadLoading.value = false
    }
  }

  watch(
    () => selectedSummaryLog.value?.id ?? null,
    resetSummaryPayload,
  )

  return {
    loadSummaryPayloadIfNeeded,
    selectedSummaryLog,
    summaryPayloadLoaded,
    summaryPayloadLoading,
    summaryPreview,
    summaryText,
  }
}
