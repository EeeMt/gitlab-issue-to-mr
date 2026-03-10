<template>
  <div>
    <n-space vertical :size="16">
      <h2>Configuration</h2>

      <n-card title="Runtime Settings">
        <n-spin :show="loading">
          <n-form ref="formRef" :model="formValue" :rules="rules">
            <n-form-item label="Max Concurrency" path="max_concurrency">
              <n-input-number v-model:value="formValue.max_concurrency" :min="1" :max="20" style="width: 200px" />
              <template #feedback>
                Maximum number of tasks that can run simultaneously
              </template>
            </n-form-item>

            <n-form-item label="Task Timeout (seconds)" path="task_timeout">
              <n-input-number v-model:value="formValue.task_timeout" :min="60" :max="7200" style="width: 200px" />
              <template #feedback>
                Maximum time a task can run before being marked as failed
              </template>
            </n-form-item>

            <n-form-item label="Scheduler Interval (seconds)" path="scheduler_interval">
              <n-input-number v-model:value="formValue.scheduler_interval" :min="1" :max="60" style="width: 200px" />
              <template #feedback>
                How often the scheduler checks for new tasks
              </template>
            </n-form-item>

            <n-form-item label="Default Target Branch" path="default_target_branch">
              <n-input v-model:value="formValue.default_target_branch" style="width: 200px" />
              <template #feedback>
                Default branch to create MRs against
              </template>
            </n-form-item>

            <n-form-item>
              <n-space>
                <n-button type="primary" @click="handleSave" :loading="saving">
                  Save
                </n-button>
                <n-button @click="handleReset">
                  Reset
                </n-button>
              </n-space>
            </n-form-item>
          </n-form>
        </n-spin>
      </n-card>
    </n-space>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { NCard, NForm, NFormItem, NInputNumber, NInput, NButton, NSpin, NSpace, useMessage, FormInst, FormRules } from 'naive-ui'
import { getConfig, updateConfig, type Config } from '../api'

const message = useMessage()

const loading = ref(false)
const saving = ref(false)
const formRef = ref<FormInst | null>(null)

const formValue = ref<Config>({
  max_concurrency: 3,
  task_timeout: 1800,
  scheduler_interval: 5,
  default_target_branch: 'main'
})

const rules: FormRules = {
  max_concurrency: {
    required: true,
    type: 'number',
    message: 'Please enter max concurrency',
    trigger: 'blur'
  },
  task_timeout: {
    required: true,
    type: 'number',
    message: 'Please enter task timeout',
    trigger: 'blur'
  },
  scheduler_interval: {
    required: true,
    type: 'number',
    message: 'Please enter scheduler interval',
    trigger: 'blur'
  },
  default_target_branch: {
    required: true,
    message: 'Please enter default target branch',
    trigger: 'blur'
  }
}

async function fetchConfig() {
  loading.value = true
  try {
    const config = await getConfig()
    formValue.value = config
  } catch (error) {
    message.error('Failed to fetch config')
  } finally {
    loading.value = false
  }
}

async function handleSave() {
  saving.value = true
  try {
    await updateConfig(formValue.value)
    message.success('Configuration saved')
  } catch (error) {
    message.error('Failed to save config')
  } finally {
    saving.value = false
  }
}

function handleReset() {
  fetchConfig()
}

onMounted(() => {
  fetchConfig()
})
</script>
