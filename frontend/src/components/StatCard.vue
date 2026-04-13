<template>
  <n-card
    size="small"
    :bordered="false"
    class="stat-card"
    :style="{ '--stat-card-accent': color }"
  >
    <div class="stat-card__body">
      <div class="stat-card__icon-wrap">
        <n-icon :size="22" :color="color" :component="icon" />
      </div>
      <div class="stat-card__content">
        <div class="stat-card__value">{{ value }}{{ suffix }}</div>
        <div class="stat-card__label">{{ label }}</div>
      </div>
    </div>
  </n-card>
</template>

<script setup lang="ts">
import { NCard, NIcon } from 'naive-ui'
import type { Component } from 'vue'

defineProps<{
  label: string
  value: string | number
  icon: Component
  color: string
  suffix?: string
}>()
</script>

<style scoped>
.stat-card {
  border-radius: var(--app-card-radius, 12px);
  border-left: 4px solid var(--stat-card-accent, #2080f0);
  background: var(--n-color);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.06);
  min-height: 80px;
}

.stat-card__body {
  display: flex;
  align-items: center;
  gap: 14px;
}

.stat-card__icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 44px;
  height: 44px;
  border-radius: 10px;
  background: color-mix(in srgb, var(--stat-card-accent) 10%, transparent);
  flex-shrink: 0;
}

.stat-card__value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  color: var(--n-text-color);
}

.stat-card__label {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-top: 2px;
}
</style>
