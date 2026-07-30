import { MERMAID_ASSET_DIR } from './mermaidAssetPath'

export type MermaidApi = typeof import('mermaid').default

let loadPromise: Promise<MermaidApi> | null = null

export function loadMermaid(): Promise<MermaidApi> {
  if (loadPromise) return loadPromise

  const baseUrl = new URL(import.meta.env.BASE_URL, window.location.href)
  const entryUrl = new URL(`${MERMAID_ASSET_DIR}/mermaid.esm.min.mjs`, baseUrl).href
  loadPromise = import(/* @vite-ignore */ entryUrl)
    .then((module) => module.default as MermaidApi)
    .catch((error) => {
      loadPromise = null
      throw error
    })

  return loadPromise
}
