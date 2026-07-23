<template>
  <div v-if="terminalHtml" class="raw-log-viewer">
    <div v-if="truncated" class="raw-log-window-notice">
      {{ t('taskView.rawLogsDisplayTruncated') }}
    </div>
    <pre ref="logContentRef" class="log-content" v-html="terminalHtml"></pre>
  </div>
  <n-empty v-else :description="t('taskView.noLogsAvailable')" class="empty-state" />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NEmpty } from 'naive-ui'
import { useI18n } from 'vue-i18n'

withDefaults(defineProps<{
  terminalHtml: string
  truncated?: boolean
}>(), {
  terminalHtml: '',
  truncated: false,
})

const logContentRef = ref<HTMLElement | null>(null)
const { t } = useI18n()

defineExpose({ logContentRef })
</script>

<style scoped>
.raw-log-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}
.raw-log-window-notice {
  padding: 8px 12px;
  border-radius: 8px 8px 0 0;
  background: rgba(245, 158, 11, 0.12);
  color: var(--n-warning-color, #d97706);
  font-size: 12px;
}
.log-content {
  flex: 1 1 auto;
  min-height: 0;
  background: #1e1e1e;
  color: #d4d4d4;
  padding: 16px;
  border-radius: 10px;
  max-height: 400px;
  overflow: auto;
  font-family: 'Consolas', 'Monaco', 'Courier New', monospace;
  font-size: 12px;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 0;
}
.raw-log-window-notice + .log-content {
  border-radius: 0 0 10px 10px;
}
.empty-state {
  padding: 24px 0;
}
</style>
