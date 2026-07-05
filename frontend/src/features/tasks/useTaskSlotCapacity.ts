import { onUnmounted, ref, watch, type Ref } from 'vue'

import { getSlotCapacity, type SlotCapacityInfo } from '../../api'

interface TaskSlotCapacityOptions {
  scheduledAt: Ref<number | null>
  enabled: Readonly<Ref<boolean>>
}

export function useTaskSlotCapacity(options: TaskSlotCapacityOptions) {
  const slotCapacity = ref<SlotCapacityInfo | null>(null)
  const slotCapacityLoading = ref(false)
  let checkTimeout: ReturnType<typeof setTimeout> | undefined
  let checkGeneration = 0

  function checkSlotCapacity() {
    slotCapacity.value = null
    slotCapacityLoading.value = false
    if (checkTimeout) clearTimeout(checkTimeout)
    checkGeneration += 1

    const scheduledAt = options.scheduledAt.value
    if (!scheduledAt) return

    const generation = checkGeneration
    checkTimeout = setTimeout(async () => {
      slotCapacityLoading.value = true
      try {
        const result = await getSlotCapacity(new Date(scheduledAt).toISOString())
        if (generation !== checkGeneration) return
        slotCapacity.value = result
      } catch {
        if (generation !== checkGeneration) return
        slotCapacity.value = null
      } finally {
        if (generation === checkGeneration) slotCapacityLoading.value = false
      }
    }, 300)
  }

  watch(options.scheduledAt, () => {
    if (options.enabled.value) checkSlotCapacity()
  })

  onUnmounted(() => {
    if (checkTimeout) clearTimeout(checkTimeout)
    checkGeneration += 1
  })

  return {
    checkSlotCapacity,
    slotCapacity,
    slotCapacityLoading,
  }
}
