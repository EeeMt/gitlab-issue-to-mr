<template>
  <div v-if="traceId" class="trace-badge" @click="copy">
    🆔 {{ traceId }}
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { getLastTraceId } from '../api/interceptors'

const traceId = ref('')

onMounted(() => {
  // 定期更新
  const update = () => {
    traceId.value = getLastTraceId()
  }
  update()
  setInterval(update, 1000)
})

function copy() {
  navigator.clipboard.writeText(traceId.value)
}
</script>

<style scoped>
.trace-badge {
  position: fixed;
  bottom: 16px;
  right: 16px;
  padding: 8px 12px;
  background: rgba(0, 0, 0, 0.7);
  color: #fff;
  font-size: 12px;
  font-family: monospace;
  border-radius: 6px;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.trace-badge:hover {
  opacity: 1;
}
</style>
