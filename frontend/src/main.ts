import { createApp } from 'vue'
import App from './App.vue'
import { i18n } from './i18n'
import router from './router'
import ErrorToast from './components/ErrorToast.vue'
import '@fontsource/inter/400.css'
import '@fontsource/inter/500.css'
import '@fontsource/inter/600.css'

const app = createApp(App)
app.use(i18n)
app.use(router)

// 全局错误提示组件
const errorToast = createApp(ErrorToast)
const errorToastMount = errorToast.mount(document.createElement('div'))
document.body.appendChild(errorToastMount.$el)

// 暴露到全局
;(window as any).__errorToast = errorToastMount

// 错误处理
app.config.errorHandler = (err, _instance, info) => {
  console.error('Vue Error:', err, info)
}

// React 风格错误边界（如果使用）
// app.config.errorCaptured = ...

app.mount('#app')
