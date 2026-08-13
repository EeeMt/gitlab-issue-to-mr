<template>
  <span class="truncated-option-label" :title="label">{{ label }}</span>
</template>

<script setup lang="ts">
defineProps<{
  label: string
}>()
</script>

<style scoped>
.truncated-option-label {
  display: block;
  min-width: 0;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
