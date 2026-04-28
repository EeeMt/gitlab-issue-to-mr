<template>
  <div :class="['summary-card', cardClass]">
    <div v-if="icon" class="summary-card__icon-ring" :class="[iconRingClass, accent && `summary-card__icon-ring--${accent}`]">
      <n-icon :component="icon" :size="20" />
    </div>
    <div class="summary-card__body">
      <div :class="['summary-card__value', valueClass]">{{ value }}</div>
      <div :class="['summary-card__label', labelClass]">{{ label }}</div>
      <div v-if="note" :class="['summary-card__note', noteClass]">{{ note }}</div>
    </div>
    <slot />
  </div>
</template>

<script setup lang="ts">
import type { Component } from 'vue'
import { NIcon } from 'naive-ui'

defineProps<{
  label: string
  value: string
  icon?: Component
  accent?: 'blue' | 'purple' | 'red' | 'green' | 'amber'
  iconRingClass?: string
  note?: string
  cardClass?: string
  labelClass?: string
  valueClass?: string
  noteClass?: string
}>()
</script>

<style scoped>
.summary-card {
  position: relative;
  display: flex;
  align-items: center;
  gap: 14px;
  box-sizing: border-box;
  padding: 16px 20px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.82);
  backdrop-filter: blur(12px);
  border: 1px solid rgba(15, 23, 42, 0.06);
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  transition:
    transform 0.25s cubic-bezier(0.22, 0.61, 0.36, 1),
    box-shadow 0.25s ease,
    border-color 0.25s ease;
}

.summary-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(15, 23, 42, 0.08);
  border-color: rgba(15, 23, 42, 0.1);
}

/* Icon ring */
.summary-card__icon-ring {
  flex-shrink: 0;
  width: 42px;
  height: 42px;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: 12px;
  background: rgba(15, 23, 42, 0.04);
  color: rgba(15, 23, 42, 0.55);
}

.summary-card__icon-ring--blue {
  background: rgba(59, 130, 246, 0.1);
  color: #3b82f6;
}

.summary-card__icon-ring--purple {
  background: rgba(139, 92, 246, 0.1);
  color: #8b5cf6;
}

.summary-card__icon-ring--red {
  background: rgba(239, 68, 68, 0.1);
  color: #ef4444;
}

.summary-card__icon-ring--green {
  background: rgba(34, 197, 94, 0.1);
  color: #22c55e;
}

.summary-card__icon-ring--amber {
  background: rgba(245, 158, 11, 0.1);
  color: #f59e0b;
}

/* Body */
.summary-card__body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.summary-card__value {
  font-size: 22px;
  font-weight: 700;
  line-height: 1.2;
  color: #0f172a;
  letter-spacing: -0.02em;
  font-variant-numeric: tabular-nums;
}

.summary-card__label {
  font-size: 12px;
  color: rgba(15, 23, 42, 0.5);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.summary-card__note {
  margin-top: 6px;
  font-size: 11px;
  line-height: 1.4;
  color: rgba(15, 23, 42, 0.45);
}

@media (hover: none) {
  .summary-card:hover {
    transform: none;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.04);
  }
}
</style>
