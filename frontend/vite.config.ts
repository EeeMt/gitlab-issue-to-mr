import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { gitCommitDefine } from './build-info'

export default defineConfig({
  plugins: [vue()],
  define: gitCommitDefine(),
  server: {
    host: '0.0.0.0',
    port: 5173,
    proxy: {
      '/api': {
        target: 'http://192.168.50.129:8000',
        changeOrigin: true,
      }
    }
  }
})
