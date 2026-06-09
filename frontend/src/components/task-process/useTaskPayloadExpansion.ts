import { reactive, ref } from 'vue'
import { getTaskPayload } from '../../api'

export function useTaskPayloadExpansion() {
  const expandedPayloads = ref<Record<number, string>>({})
  const loadingPayloads = ref<Set<number>>(new Set())
  const payloadLoadErrors = reactive<Record<number, boolean>>({})

  async function loadPayload(taskId: number, payloadId: number) {
    if (expandedPayloads.value[payloadId] !== undefined || loadingPayloads.value.has(payloadId)) return
    loadingPayloads.value = new Set([...loadingPayloads.value, payloadId])
    delete payloadLoadErrors[payloadId]
    try {
      const payload = await getTaskPayload(taskId, payloadId)
      expandedPayloads.value = { ...expandedPayloads.value, [payloadId]: payload.content }
    } catch {
      payloadLoadErrors[payloadId] = true
    } finally {
      const next = new Set(loadingPayloads.value)
      next.delete(payloadId)
      loadingPayloads.value = next
    }
  }

  function isPayloadLoading(payloadId: number | null): boolean {
    return payloadId !== null && loadingPayloads.value.has(payloadId)
  }

  function isPayloadLoaded(payloadId: number | null): boolean {
    return payloadId !== null && expandedPayloads.value[payloadId] !== undefined
  }

  function getExpandedPayloadText(payloadId: number | null): string | undefined {
    return payloadId !== null ? expandedPayloads.value[payloadId] : undefined
  }

  function hasPayloadLoadError(payloadId: number | null): boolean {
    return payloadId !== null && !!payloadLoadErrors[payloadId]
  }

  return {
    expandedPayloads,
    loadingPayloads,
    payloadLoadErrors,
    loadPayload,
    isPayloadLoading,
    isPayloadLoaded,
    getExpandedPayloadText,
    hasPayloadLoadError,
  }
}
