<template>
  <div class="system-init-banner">
    <n-icon size="14" class="system-init-banner__icon"><ServerOutline /></n-icon>
    <span v-if="entry.model">{{ t('taskView.modelName') }}: <strong>{{ entry.model }}</strong></span>
    <span v-if="entry.model && entry.cwd" class="system-init-banner__sep">|</span>
    <span v-if="entry.cwd">CWD: <code class="system-init-banner__value">{{ entry.cwd }}</code></span>
    <span v-if="hasContainerSeparator" class="system-init-banner__sep">|</span>
    <span v-if="containerId">
      {{ t('taskView.container') }}:
      <code class="system-init-banner__value">{{ containerName ?? containerId.slice(0, 12) }}</code>
    </span>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { NIcon } from 'naive-ui'
import { ServerOutline } from '@vicons/ionicons5'
import { useI18n } from 'vue-i18n'

const props = defineProps<{
  entry: {
    model: string | null
    cwd: string | null
  }
  containerId?: string | null
  containerName?: string | null
}>()

const { t } = useI18n()
const hasContainerSeparator = computed(() => !!props.containerId && (!!props.entry.model || !!props.entry.cwd))
</script>

<style scoped>
.system-init-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  padding: 7px 12px;
  margin-bottom: 12px;
  background: rgba(128, 128, 128, 0.06);
  border-radius: 8px;
  font-size: 12px;
  color: var(--n-text-color-2, #666);
  border-left: 3px solid rgba(128, 128, 128, 0.25);
}
.system-init-banner__icon {
  color: var(--n-text-color-3, #999);
  flex-shrink: 0;
}
.system-init-banner__sep {
  opacity: 0.4;
}
.system-init-banner__value {
  font-family: var(--n-font-family-mono, monospace);
  font-size: 11px;
  background: rgba(128, 128, 128, 0.1);
  padding: 1px 5px;
  border-radius: 3px;
}
</style>
