import { ref } from 'vue'

import {
  getConfig,
  getScheduledTasks,
  type Task,
} from '../../api'

export function useTaskScheduleContext() {
  const scheduledTasks = ref<Task[]>([])
  const scheduledTasksLoading = ref(false)
  const slotMaxTasks = ref(0)
  const slotEnforce = ref(false)
  const slotConfigLoadFailed = ref(false)

  async function loadScheduleContext(forceTasks = false) {
    if (forceTasks || scheduledTasks.value.length === 0) {
      scheduledTasksLoading.value = true
      try {
        scheduledTasks.value = await getScheduledTasks()
      } catch {
        scheduledTasks.value = []
      } finally {
        scheduledTasksLoading.value = false
      }
    }

    slotConfigLoadFailed.value = false
    try {
      const config = await getConfig()
      slotMaxTasks.value = config.runtime?.slot_max_tasks ?? 0
      slotEnforce.value = config.runtime?.slot_max_tasks_enforce ?? false
    } catch {
      slotConfigLoadFailed.value = true
    }
  }

  function clearScheduledTasks() {
    scheduledTasks.value = []
  }

  return {
    scheduledTasks,
    scheduledTasksLoading,
    slotMaxTasks,
    slotEnforce,
    slotConfigLoadFailed,
    loadScheduleContext,
    clearScheduledTasks,
  }
}
