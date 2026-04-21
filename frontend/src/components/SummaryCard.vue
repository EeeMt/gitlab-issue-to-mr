<template>
  <n-card
    size="small"
    :bordered="false"
    :class="['summary-card', cardClass]"
  >
    <div :class="['summary-card__label', labelClass]">{{ label }}</div>
    <div :class="['summary-card__value', valueClass]">{{ value }}</div>
    <div v-if="note" :class="['summary-card__note', noteClass]">{{ note }}</div>
    <slot />
  </n-card>
</template>

<script setup lang="ts">
import { NCard } from 'naive-ui'

defineProps<{
  label: string
  value: string
  note?: string
  cardClass?: string
  labelClass?: string
  valueClass?: string
  noteClass?: string
}>()
</script>

<style scoped>
.summary-card {
  border-radius: var(--app-card-radius, 18px);
  background: var(
    --app-summary-card-background,
    linear-gradient(180deg, rgba(32, 128, 240, 0.06), rgba(32, 128, 240, 0.02))
  );
  box-shadow: var(--app-card-shadow-soft, 0 10px 24px rgba(15, 23, 42, 0.05));
}

.summary-card__label {
  margin-bottom: 8px;
  font-size: 12px;
  color: var(--app-page-subtitle-color, rgba(15, 23, 42, 0.68));
}

.summary-card__value {
  font-size: 20px;
  font-weight: 600;
  color: var(--n-text-color-1);
}

.summary-card__note {
  margin-top: 8px;
  font-size: 12px;
  line-height: 1.4;
  color: rgba(15, 23, 42, 0.6);
}
</style>
