<template>
  <n-card
    v-if="visible"
    class="task-steering-panel"
    :bordered="false"
    data-testid="steering-panel"
  >
    <template #header>
      <div class="steering-panel__header">
        <span class="steering-panel__title">{{ t('taskView.steeringTitle') }}</span>
        <span
          class="steering-panel__gate"
          :class="`steering-panel__gate--${controlState}`"
          :data-testid="`steering-gate-${controlState}`"
        >{{ gateLabel }}</span>
      </div>
    </template>

    <div class="steering-panel__content">
      <n-radio-group
        v-model:value="commandType"
        class="steering-panel__mode-select"
        size="small"
        :disabled="!inputEnabled"
      >
        <n-radio-button value="steer" :disabled="!steeringSupported">{{ t('taskView.steeringSteer') }}</n-radio-button>
        <n-radio-button value="follow_up" :disabled="!followUpSupported">{{ t('taskView.steeringFollowUp') }}</n-radio-button>
      </n-radio-group>

      <n-input
        class="steering-panel__input"
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
          class="steering-panel__send"
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

      <ul v-if="history.length" class="steering-panel__history" data-testid="steering-history">
        <li v-for="cmd in history" :key="cmd.command_id" class="steering-panel__history-item">
          <span class="steering-panel__history-type">{{ cmd.type === 'steer' ? t('taskView.steeringSteer') : t('taskView.steeringFollowUp') }}</span>
          <span class="steering-panel__history-sequence">#{{ cmd.sequence_no }}</span>
          <span class="steering-panel__history-status" :data-testid="`steering-command-${cmd.status}`">{{ commandStatusLabel(cmd.status) }}</span>
          <time class="steering-panel__history-time">{{ commandTime(cmd) }}</time>
          <span v-if="cmd.rejection_message" class="steering-panel__history-rejection">{{ cmd.rejection_message }}</span>
        </li>
      </ul>

      <p class="steering-panel__note">{{ t('taskView.steeringNote') }}</p>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { NButton, NCard, NInput, NRadioButton, NRadioGroup, useMessage } from 'naive-ui'
import { listHarnessCommands, sendHarnessCommand, type HarnessCommand } from '../api/tasks'

const props = defineProps<{
  taskId: number
  taskStatus: string
  controlState: string | null | undefined
  capabilities: { steering?: boolean; follow_up?: boolean } | null | undefined
}>()

const emit = defineEmits<{ (e: 'command-delivered'): void }>()

const { t } = useI18n()
const message = useMessage()

const commandType = ref<'steer' | 'follow_up'>('steer')
const text = ref('')
const sending = ref(false)
const history = ref<HarnessCommand[]>([])
let historyRequestGeneration = 0

const steeringSupported = computed(() => props.capabilities?.steering === true)
const followUpSupported = computed(() => props.capabilities?.follow_up === true)

const visible = computed(() => {
  if (!steeringSupported.value && !followUpSupported.value) return false
  return ['running', 'completed', 'failed', 'cancelled'].includes(props.taskStatus)
})

// A catalog-capable attempt with a live control gate accepts commands;
// completed runs keep the panel for read-only history.
const inputEnabled = computed(
  () => props.taskStatus === 'running'
    && props.controlState === 'accepting'
    && (commandType.value === 'steer' ? steeringSupported.value : followUpSupported.value)
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

const COMMAND_STATUS_I18N_KEYS: Record<HarnessCommand['status'], string> = {
  queued: 'taskView.steeringStatusQueued',
  dispatching: 'taskView.steeringStatusDispatching',
  delivered: 'taskView.steeringStatusDelivered',
  rejected: 'taskView.steeringStatusRejected',
  outcome_unknown: 'taskView.steeringStatusOutcomeUnknown',
}

function commandStatusLabel(status: string): string {
  const key = COMMAND_STATUS_I18N_KEYS[status as HarnessCommand['status']]
  // The server should only return the frozen lifecycle above.  Do not turn a
  // future/bad value into a missing i18n key in the operator control plane.
  return key ? t(key) : 'Unknown'
}

function commandTime(command: HarnessCommand): string {
  const value = command.native_ack_at
    ?? command.delivered_at
    ?? command.outcome_unknown_at
    ?? command.rejected_at
    ?? command.dispatch_started_at
    ?? command.created_at
  if (!value) return ''
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function refreshHistory(): Promise<void> {
  const requestGeneration = ++historyRequestGeneration
  const requestedTaskId = props.taskId
  try {
    const commands = await listHarnessCommands(requestedTaskId)
    if (requestGeneration === historyRequestGeneration && requestedTaskId === props.taskId) {
      history.value = commands
    }
  } catch {
    if (requestGeneration === historyRequestGeneration && requestedTaskId === props.taskId) {
      history.value = []
    }
  }
}

watch(
  () => [props.taskId, props.taskStatus, props.controlState, steeringSupported.value, followUpSupported.value],
  (current, previous) => {
    const taskChanged = previous !== undefined && current[0] !== previous[0]
    if (taskChanged) {
      // Do this synchronously so a route transition never shows another task's draft/history.
      historyRequestGeneration += 1
      history.value = []
      text.value = ''
    }
    if (visible.value) {
      void refreshHistory()
    } else if (taskChanged) {
      history.value = []
    }
  },
  { immediate: true }
)

watch([steeringSupported, followUpSupported], ([steering, followUp]) => {
  if (commandType.value === 'steer' && !steering && followUp) commandType.value = 'follow_up'
  if (commandType.value === 'follow_up' && !followUp && steering) commandType.value = 'steer'
}, { immediate: true })

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
.task-steering-panel {
  border-radius: var(--app-card-radius);
}

.steering-panel__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;
}

.steering-panel__title {
  min-width: 0;
  color: var(--n-text-color-1);
  font-size: 16px;
  font-weight: 600;
  line-height: 1.35;
}

.steering-panel__gate {
  display: inline-flex;
  align-items: center;
  flex: 0 0 auto;
  max-width: 100%;
  padding: 3px 9px;
  border: 1px solid rgba(100, 116, 139, 0.18);
  border-radius: 999px;
  background: rgba(100, 116, 139, 0.08);
  color: var(--n-text-color-2, #64748b);
  font-size: 11px;
  font-weight: 600;
  line-height: 1.35;
  white-space: nowrap;
}

.steering-panel__gate--accepting {
  border-color: rgba(24, 160, 88, 0.18);
  background: rgba(24, 160, 88, 0.08);
  color: var(--n-primary-color, #18a058);
}

.steering-panel__gate--starting,
.steering-panel__gate--closing {
  border-color: rgba(217, 119, 6, 0.2);
  background: rgba(217, 119, 6, 0.08);
  color: #b45309;
}

.steering-panel__content {
  display: flex;
  flex-direction: column;
  gap: 12px;
  min-width: 0;
}

.steering-panel__mode-select {
  align-self: flex-start;
  max-width: 100%;
  --n-button-border-color: rgba(15, 23, 42, 0.12) !important;
  --n-button-border-color-active: rgba(37, 99, 235, 0.28) !important;
  --n-button-border-radius: 8px !important;
  --n-button-color: rgba(255, 255, 255, 0.68) !important;
  --n-button-color-active: rgba(37, 99, 235, 0.1) !important;
  --n-button-text-color: rgba(51, 65, 85, 0.92) !important;
  --n-button-text-color-active: #1d4ed8 !important;
  --n-button-text-color-hover: rgba(30, 41, 59, 0.96) !important;
}

.steering-panel__input {
  width: 100%;
  --n-border: 1px solid rgba(15, 23, 42, 0.12) !important;
  --n-border-focus: 1px solid rgba(37, 99, 235, 0.28) !important;
  --n-border-hover: 1px solid rgba(15, 23, 42, 0.18) !important;
  --n-border-radius: 8px !important;
  --n-box-shadow-focus: 0 0 0 2px rgba(37, 99, 235, 0.08) !important;
  --n-color: rgba(255, 255, 255, 0.68) !important;
  --n-color-focus: rgba(248, 250, 252, 0.96) !important;
  --n-padding-left: 12px !important;
  --n-padding-right: 12px !important;
}

.steering-panel__footer {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
}

.steering-panel__send {
  flex: 0 0 auto;
  min-width: 72px;
  --n-border-radius: 8px !important;
  --n-font-weight: 600 !important;
  --n-height: 34px !important;
  --n-padding: 0 12px !important;
  --n-ripple-color: rgba(37, 99, 235, 0.18) !important;
}

.steering-panel__hint {
  min-width: 0;
  flex: 1 1 220px;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 12px;
  line-height: 1.45;
}

.steering-panel__note {
  margin: 0;
  color: var(--n-text-color-3, #8a8f98);
  font-size: 11px;
  line-height: 1.45;
}

.steering-panel__history {
  list-style: none;
  margin: 2px 0 0;
  padding: 0;
  padding-top: 12px;
  border-top: 1px solid rgba(15, 23, 42, 0.08);
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-height: 160px;
  overflow-y: auto;
}

.steering-panel__history-item {
  display: flex;
  gap: 6px;
  align-items: baseline;
  flex-wrap: wrap;
  min-width: 0;
  font-size: 12px;
}

.steering-panel__history-type {
  color: #18a058;
  white-space: nowrap;
  font-weight: 500;
}

.steering-panel__history-sequence,
.steering-panel__history-time {
  color: #888;
  white-space: nowrap;
}

.steering-panel__history-status {
  color: #999;
  white-space: nowrap;
}

.steering-panel__history-rejection {
  flex-basis: 100%;
  overflow-wrap: anywhere;
  color: #d03050;
}

@media (max-width: 767px) {
  .task-steering-panel :deep(.n-radio-button),
  .task-steering-panel :deep(.n-button) {
    min-height: 44px;
  }
}
</style>
