<template>
  <div v-if="visible" class="steering-panel" data-testid="steering-panel">
    <div class="steering-panel__header">
      <span class="steering-panel__title">{{ t('taskView.steeringTitle') }}</span>
      <span
        class="steering-panel__gate"
        :class="`steering-panel__gate--${controlState}`"
        :data-testid="`steering-gate-${controlState}`"
      >{{ gateLabel }}</span>
    </div>

    <n-radio-group v-model:value="commandType" size="small" :disabled="!inputEnabled">
      <n-radio-button value="steer">{{ t('taskView.steeringSteer') }}</n-radio-button>
      <n-radio-button value="follow_up">{{ t('taskView.steeringFollowUp') }}</n-radio-button>
    </n-radio-group>

    <n-input
      v-model:value="text"
      type="textarea"
      :rows="2"
      maxlength="4000"
      show-count
      :disabled="!inputEnabled || sending"
      :placeholder="t('taskView.steeringPlaceholder')"
      data-testid="steering-input"
    />

    <div class="steering-panel__footer">
      <n-button
        size="small"
        type="primary"
        :loading="sending"
        :disabled="!inputEnabled || !text.trim() || sending"
        data-testid="steering-send"
        @click="send"
      >
        {{ t('taskView.steeringSend') }}
      </n-button>
      <span v-if="hintText" class="steering-panel__hint" data-testid="steering-hint">
        {{ hintText }}
      </span>
    </div>

    <ul v-if="deliveredCommands.length" class="steering-panel__history" data-testid="steering-history">
      <li v-for="cmd in deliveredCommands" :key="cmd.command_id" class="steering-panel__history-item">
        <span class="steering-panel__history-type">{{ cmd.command_type === 'steer' ? t('taskView.steeringSteer') : t('taskView.steeringFollowUp') }}</span>
        <span class="steering-panel__history-text">{{ cmd.payload.text }}</span>
        <span class="steering-panel__history-status">{{ t('taskView.steeringDelivered') }}</span>
      </li>
    </ul>

    <p class="steering-panel__note">{{ t('taskView.steeringNote') }}</p>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NInput, NRadioButton, NRadioGroup, useMessage } from 'naive-ui'
import { listHarnessCommands, sendHarnessCommand, type HarnessCommand } from '../api/tasks'

const props = defineProps<{
  taskId: number
  taskStatus: string
  harnessKey: string | null | undefined
  controlState: string | null | undefined
}>()

const emit = defineEmits<{ (e: 'command-delivered'): void }>()

const { t } = useI18n()
const message = useMessage()

const commandType = ref<'steer' | 'follow_up'>('steer')
const text = ref('')
const sending = ref(false)
const history = ref<HarnessCommand[]>([])

const CONTROL_CAPABLE = new Set(['pi'])

const visible = computed(() => {
  if (!CONTROL_CAPABLE.has(props.harnessKey ?? '')) return false
  return ['running', 'completed', 'failed', 'cancelled'].includes(props.taskStatus)
})

// Only Pi attempts with a live control gate accept commands; completed runs
// keep the panel for read-only history.
const inputEnabled = computed(
  () => props.taskStatus === 'running' && props.controlState === 'accepting'
)

const gateLabel = computed(() => {
  switch (props.controlState) {
    case 'starting':
      return t('taskView.steeringGateStarting')
    case 'accepting':
      return t('taskView.steeringGateAccepting')
    case 'closing':
      return t('taskView.steeringGateClosing')
    case 'closed':
      return t('taskView.steeringGateClosed')
    default:
      return ''
  }
})

const hintText = computed(() => {
  if (props.taskStatus !== 'running') return ''
  if (props.controlState === 'starting') return t('taskView.steeringHintStarting')
  if (props.controlState === 'closing') return t('taskView.steeringHintClosing')
  return ''
})

const deliveredCommands = computed(() =>
  history.value.filter(cmd => cmd.status === 'delivered')
)

async function refreshHistory(): Promise<void> {
  try {
    history.value = await listHarnessCommands(props.taskId)
  } catch {
    history.value = []
  }
}

watch(
  () => [props.taskId, props.controlState],
  () => {
    text.value = ''
    if (visible.value) void refreshHistory()
  },
  { immediate: true }
)

async function send(): Promise<void> {
  const body = text.value.trim()
  if (!body || sending.value) return
  sending.value = true
  try {
    const result = await sendHarnessCommand(props.taskId, {
      type: commandType.value,
      text: body,
    })
    text.value = ''
    if (result.command.status === 'delivered') {
      message.success(t('taskView.steeringDeliveredToast'))
      emit('command-delivered')
    } else if (result.command.status === 'queued') {
      message.info(t('taskView.steeringQueuedToast'))
    } else {
      message.warning(
        `${t('taskView.steeringRejectedToast')}: ${result.command.rejection_message ?? ''}`
      )
    }
    await refreshHistory()
  } catch (err) {
    const detail =
      (err as { response?: { data?: { detail?: string | { msg?: string }[] } } })
        ?.response?.data?.detail
    const msg =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map(d => d.msg ?? '').join('; ')
          : ''
    message.error(`${t('taskView.steeringFailedToast')}${msg ? `: ${msg}` : ''}`)
  } finally {
    sending.value = false
  }
}
</script>

<style scoped>
.steering-panel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1px solid var(--n-border-color, #e0e0e6);
  border-radius: 6px;
  margin-bottom: 12px;
}

.steering-panel__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.steering-panel__title {
  font-weight: 600;
  font-size: 13px;
}

.steering-panel__gate {
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 10px;
  background: #f0f0f0;
}

.steering-panel__gate--accepting {
  background: #e8f7ee;
  color: #18a058;
}

.steering-panel__gate--starting,
.steering-panel__gate--closing {
  background: #fff7e6;
  color: #d48806;
}

.steering-panel__footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.steering-panel__hint {
  font-size: 12px;
  color: #999;
}

.steering-panel__note {
  margin: 0;
  font-size: 11px;
  color: #aaa;
}

.steering-panel__history {
  list-style: none;
  margin: 4px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 160px;
  overflow-y: auto;
}

.steering-panel__history-item {
  display: flex;
  gap: 6px;
  align-items: baseline;
  font-size: 12px;
}

.steering-panel__history-type {
  color: #18a058;
  white-space: nowrap;
  font-weight: 500;
}

.steering-panel__history-text {
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.steering-panel__history-status {
  color: #999;
  white-space: nowrap;
}
</style>
