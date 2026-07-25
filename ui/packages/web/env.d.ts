/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AI_HUB_URL: string
  readonly VITE_AI_HUB_APP_CODE: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, unknown>
  export default component
}
