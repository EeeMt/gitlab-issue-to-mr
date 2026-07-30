import { readFile, readdir } from 'node:fs/promises'
import { join, relative, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import type { Plugin } from 'vite'

import { MERMAID_ASSET_DIR } from '../src/vendor/mermaidAssetPath'

const mermaidDistDir = fileURLToPath(new URL('../node_modules/mermaid/dist/', import.meta.url))

export function mermaidAssets(): Plugin[] {
  return [
    {
      name: 'codify-mermaid-assets-build',
      apply: 'build',
      async buildStart() {
        const entrySource = await readFile(join(mermaidDistDir, 'mermaid.esm.min.mjs'))
        this.emitFile({
          type: 'asset',
          fileName: `${MERMAID_ASSET_DIR}/mermaid.esm.min.mjs`,
          source: entrySource,
        })

        const chunksDir = join(mermaidDistDir, 'chunks', 'mermaid.esm.min')
        const chunks = await readdir(chunksDir, { withFileTypes: true })
        await Promise.all(chunks
          .filter((chunk) => chunk.isFile() && chunk.name.endsWith('.mjs'))
          .map(async (chunk) => {
            const source = await readFile(join(chunksDir, chunk.name))
            this.emitFile({
              type: 'asset',
              fileName: `${MERMAID_ASSET_DIR}/chunks/mermaid.esm.min/${chunk.name}`,
              source,
            })
          }))
      },
    },
    {
      name: 'codify-mermaid-assets-serve',
      apply: 'serve',
      configureServer(server) {
        server.middlewares.use(async (request, response, next) => {
          if (!request.url) return next()

          let pathname: string
          try {
            pathname = decodeURIComponent(new URL(request.url, 'http://vite.local').pathname)
          } catch {
            return next()
          }

          const prefix = `/${MERMAID_ASSET_DIR}/`
          if (!pathname.startsWith(prefix)) return next()

          const filePath = resolve(mermaidDistDir, pathname.slice(prefix.length))
          const relativePath = relative(mermaidDistDir, filePath)
          if (relativePath.startsWith('..') || !filePath.endsWith('.mjs')) {
            response.statusCode = 404
            return response.end()
          }

          try {
            const source = await readFile(filePath)
            response.statusCode = 200
            response.setHeader('Content-Type', 'text/javascript; charset=utf-8')
            response.setHeader('Cache-Control', 'no-cache')
            response.end(source)
          } catch {
            response.statusCode = 404
            response.end()
          }
        })
      },
    },
  ]
}
