<template>
  <pre v-if="terminalHtml" ref="logContentRef" class="log-content" v-html="terminalHtml"></pre>
  <n-empty v-else :description="t('taskView.noLogsAvailable')" class="empty-state" />
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { NEmpty } from 'naive-ui'
import { useI18n } from 'vue-i18n'

withDefaults(defineProps<{
  terminalHtml: string
}>(), {
  terminalHtml: ''
})

const logContentRef = ref<HTMLElement | null>(null)
const { t } = useI18n()

defineExpose({ logContentRef })
</script>

<style scoped>
.log-content {
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
.empty-state {
  padding: 24px 0;
}
</style>
