<template>
  <Teleport to="body">
    <Transition name="toast">
      <div v-if="visible" class="error-toast" @click="dismiss">
        <div class="error-toast__icon">⚠️</div>
        <div class="error-toast__content">
          <div class="error-toast__message">{{ message }}</div>
          <div class="error-toast__trace" @click.stop="copyTraceId">
            ID: {{ traceId }}
            <span class="error-toast__copy">(点击复制)</span>
          </div>
        </div>
        <button class="error-toast__close" @click.stop="dismiss">×</button>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { getLastError, getLastTraceId } from '../api/interceptors'

const visible = ref(false)
const message = ref('')
const traceId = ref('')

function showError() {
  const error = getLastError()
  if (error) {
    message.value = error.message || '操作失败'
    traceId.value = error.traceId
    visible.value = true

    // 3秒后自动消失
    setTimeout(() => {
      visible.value = false
    }, 5000)
  }
}

function dismiss() {
  visible.value = false
}

function copyTraceId() {
  navigator.clipboard.writeText(traceId.value)
  alert('Trace ID 已复制')
}

// 监听全局错误
watch(visible, (val) => {
  if (val) {
    // 重新获取最新的错误信息
    const error = getLastError()
    if (error) {
      message.value = error.message
      traceId.value = error.traceId
    }
  }
})

// 暴露显示方法
defineExpose({ showError })
</script>

<style scoped>
.error-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  display: flex;
  align-items: flex-start;
  gap: 12px;
  padding: 16px 20px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 4px 24px rgba(0, 0, 0, 0.15);
  z-index: 9999;
  max-width: 400px;
  cursor: pointer;
}

.error-toast__icon {
  font-size: 24px;
}

.error-toast__content {
  flex: 1;
}

.error-toast__message {
  font-size: 14px;
  color: #333;
  margin-bottom: 4px;
}

.error-toast__trace {
  font-size: 12px;
  color: #666;
  font-family: monospace;
}

.error-toast__copy {
  color: #1890ff;
  margin-left: 4px;
}

.error-toast__close {
  background: none;
  border: none;
  font-size: 20px;
  color: #999;
  cursor: pointer;
  padding: 0;
  line-height: 1;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.3s ease;
}

.toast-enter-from,
.toast-leave-to {
  opacity: 0;
  transform: translateX(100%);
}
</style>
