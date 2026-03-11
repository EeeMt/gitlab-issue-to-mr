<template>
  <div>
    <n-space vertical :size="16">
      <n-space align="center" justify="space-between">
        <h2>Task #{{ taskId }}</h2>
        <n-space>
          <n-button @click="refreshTask" :loading="loading">
            Refresh
          </n-button>
        </n-space>
      </n-space>

      <n-spin :show="loading">
        <n-grid :cols="2" :x-gap="16" :y-gap="16">
          <n-gi>
            <n-card title="Task Details">
              <n-descriptions :column="1" label-placement="left" v-if="task">
                <n-descriptions-item label="Status">
                  <n-tag :type="statusColors[task.status]">{{ task.status }}</n-tag>
                </n-descriptions-item>
                <n-descriptions-item label="Project ID">{{ task.project_id }}</n-descriptions-item>
                <n-descriptions-item label="Issue">!{{ task.issue_iid }}</n-descriptions-item>
                <n-descriptions-item label="Priority">{{ task.priority }}</n-descriptions-item>
                <n-descriptions-item label="Branch">{{ task.branch_name }}</n-descriptions-item>
                <n-descriptions-item label="Target Branch">{{ task.target_branch }}</n-descriptions-item>
                <n-descriptions-item label="Container ID">{{ task.container_id || '-' }}</n-descriptions-item>
                <n-descriptions-item label="MR URL">
                  <a v-if="task.merge_request_url" :href="task.merge_request_url" target="_blank">{{ task.merge_request_url }}</a>
                  <span v-else>-</span>
                </n-descriptions-item>
                <n-descriptions-item label="Created">{{ formatDate(task.created_at) }}</n-descriptions-item>
                <n-descriptions-item label="Started">{{ task.started_at ? formatDate(task.started_at) : '-' }}</n-descriptions-item>
                <n-descriptions-item label="Completed">{{ task.completed_at ? formatDate(task.completed_at) : '-' }}</n-descriptions-item>
              </n-descriptions>
            </n-card>
          </n-gi>

          <n-gi>
            <n-card title="Actions">
              <n-space vertical>
                <n-button
                  v-if="task && ['pending', 'queued', 'running'].includes(task.status)"
                  type="error"
                  @click="handleCancel"
                  :loading="actionLoading"
                >
                  Cancel Task
                </n-button>
                <n-button
                  v-if="task && ['failed', 'cancelled'].includes(task.status)"
                  type="warning"
                  @click="handleRetry"
                  :loading="actionLoading"
                >
                  Retry Task
                </n-button>
                <n-button
                  v-if="task && task.status === 'pending'"
                  type="info"
                  @click="handleExecute"
                  :loading="actionLoading"
                >
                  Execute Now
                </n-button>
              </n-space>
            </n-card>

            <n-card title="Error" style="margin-top: 16px" v-if="task?.error_message">
              <n-alert type="error">{{ task.error_message }}</n-alert>
            </n-card>
          </n-gi>
        </n-grid>

        <n-card title="User Prompt" style="margin-top: 16px" v-if="task">
          <n-text>{{ task.user_prompt }}</n-text>
        </n-card>

        <n-card title="Logs" style="margin-top: 16px">
          <template #header-extra>
            <n-space>
              <n-tag v-if="task?.status === 'running'" type="warning" size="small">Real-time</n-tag>
              <n-button size="small" @click="refreshLogs">Refresh</n-button>
            </n-space>
          </template>
          <n-spin :show="logsLoading">
            <!-- Show container logs for running tasks -->
            <div v-if="task?.status === 'running' || task?.status === 'pending' || task?.status === 'queued'">
              <n-spin :show="containerLogsLoading">
                <pre class="log-content">{{ containerLogs || 'Waiting for logs...' }}</pre>
              </n-spin>
            </div>
            <!-- Show database logs for completed/failed tasks -->
            <div v-else>
              <pre class="log-content">{{ logs || 'No logs available' }}</pre>
            </div>
          </n-spin>
        </n-card>
      </n-spin>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, computed } from 'vue'
import { useRoute } from 'vue-router'
import { NButton, NSpace, NCard, NDescriptions, NDescriptionsItem, NTag, NGrid, NGi, NSpin, NAlert, NText, useMessage } from 'naive-ui'
import { getTask, getTaskLogs, getTaskContainerLogs, cancelTask, retryTask, executeTask, type Task } from '../api'

const route = useRoute()
const message = useMessage()

const taskId = computed(() => Number(route.params.id))

const task = ref<Task | null>(null)
const logs = ref('')
const containerLogs = ref('')
const loading = ref(false)
const logsLoading = ref(false)
const containerLogsLoading = ref(false)
const actionLoading = ref(false)

const statusColors: Record<string, 'default' | 'info' | 'warning' | 'success' | 'error'> = {
  pending: 'default',
  queued: 'info',
  running: 'warning',
  completed: 'success',
  failed: 'error',
  cancelled: 'default'
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleString()
}

async function fetchTask() {
  loading.value = true
  try {
    task.value = await getTask(taskId.value)
  } catch (error) {
    message.error('Failed to fetch task')
  } finally {
    loading.value = false
  }
}

async function fetchLogs() {
  logsLoading.value = true
  try {
    const logEntries = await getTaskLogs(taskId.value)
    logs.value = logEntries.map(l => `[${l.created_at}] [${l.log_level}] ${l.message}`).join('\n')
  } catch (error) {
    logs.value = 'Failed to fetch logs'
  } finally {
    logsLoading.value = false
  }
}

async function fetchContainerLogs() {
  if (!task.value?.container_id) {
    containerLogs.value = ''
    return
  }
  containerLogsLoading.value = true
  try {
    const result = await getTaskContainerLogs(taskId.value)
    containerLogs.value = result.logs
  } catch (error) {
    containerLogs.value = 'Failed to fetch container logs'
  } finally {
    containerLogsLoading.value = false
  }
}

function refreshTask() {
  fetchTask()
  fetchLogs()
  fetchContainerLogs()
}

function refreshLogs() {
  fetchLogs()
  fetchContainerLogs()
}

async function handleCancel() {
  actionLoading.value = true
  try {
    await cancelTask(taskId.value)
    message.success('Task cancelled')
    refreshTask()
  } catch (error) {
    message.error('Failed to cancel task')
  } finally {
    actionLoading.value = false
  }
}

async function handleRetry() {
  actionLoading.value = true
  try {
    await retryTask(taskId.value)
    message.success('Task retry scheduled')
    refreshTask()
  } catch (error) {
    message.error('Failed to retry task')
  } finally {
    actionLoading.value = false
  }
}

async function handleExecute() {
  actionLoading.value = true
  try {
    await executeTask(taskId.value)
    message.success('Task execution started')
    refreshTask()
  } catch (error) {
    message.error('Failed to execute task')
  } finally {
    actionLoading.value = false
  }
}

onMounted(() => {
  fetchTask()
  fetchLogs()
  fetchContainerLogs()
  // Auto-refresh for running tasks - more frequent for container logs
  setInterval(() => {
    if (task.value?.status === 'running' || task.value?.status === 'pending' || task.value?.status === 'queued') {
      fetchTask()
      fetchContainerLogs()
    }
  }, 3000)
})
</script>

<style scoped>
.log-content {
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 4px;
  max-height: 400px;
  overflow: auto;
  font-family: 'Consolas', 'Monaco', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
