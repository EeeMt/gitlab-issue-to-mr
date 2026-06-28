/// <reference types="vite/client" />

declare const __GIT_COMMIT__: string

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}
