import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'
import { gitCommitDefine } from './build-info'
import { mermaidAssets } from './vite/mermaidAssets'

export default defineConfig({
  plugins: [vue(), ...mermaidAssets()],
  define: gitCommitDefine(),
  resolve: {
    alias: [
      {
        // The package barrel re-exports thousands of icons. Point production builds at the
        // curated project barrel so Rollup only transforms icons that Codify actually uses.
        find: /^@vicons\/ionicons5$/,
        replacement: fileURLToPath(new URL('./src/icons/ionicons5.ts', import.meta.url)),
      },
      {
        // Naive UI's top-level entry includes every component. The local entry keeps existing
        // imports intact while limiting the production module graph to components Codify uses.
        find: /^naive-ui$/,
        replacement: fileURLToPath(new URL('./src/ui/naiveUi.ts', import.meta.url)),
      },
    ],
  },
  build: {
    // Gzip reporting adds work after every build and does not affect the generated assets.
    reportCompressedSize: false,
  },
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
