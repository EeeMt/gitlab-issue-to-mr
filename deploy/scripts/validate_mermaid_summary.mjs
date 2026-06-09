#!/usr/bin/env node
import fs from 'node:fs/promises'
import { JSDOM } from 'jsdom'

const inputPath = process.argv[2]

if (!inputPath) {
  console.error('Usage: validate_mermaid_summary.mjs <markdown-file>')
  process.exit(2)
}

function installDomGlobals() {
  const dom = new JSDOM('<!doctype html><html><body></body></html>', {
    pretendToBeVisual: true,
  })

  const globals = {
    window: dom.window,
    document: dom.window.document,
    navigator: dom.window.navigator,
  }
  for (const [key, value] of Object.entries(globals)) {
    Object.defineProperty(globalThis, key, { value, configurable: true })
  }

  for (const key of ['Element', 'HTMLElement', 'SVGElement', 'XMLSerializer', 'DOMParser', 'Node']) {
    Object.defineProperty(globalThis, key, { value: dom.window[key], configurable: true })
  }

  if (!globalThis.CSSStyleSheet) {
    Object.defineProperty(globalThis, 'CSSStyleSheet', {
      configurable: true,
      value: class CSSStyleSheet {
        constructor() {
          this.cssRules = []
        }

        replaceSync(css) {
          this.cssRules = css ? [{ cssText: css }] : []
        }

        insertRule(rule, index = this.cssRules.length) {
          this.cssRules.splice(index, 0, { cssText: rule })
          return index
        }
      },
    })
  }

  if (!dom.window.SVGElement.prototype.getBBox) {
    dom.window.SVGElement.prototype.getBBox = function getBBox() {
      const text = this.textContent || ''
      return {
        x: 0,
        y: 0,
        width: Math.max(24, text.length * 8),
        height: 18,
      }
    }
  }
}

function extractMermaidDiagrams(markdown) {
  const diagrams = []
  const pattern = /(^|\n)(`{3,}|~{3,})[ \t]*mermaid[^\n]*\n([\s\S]*?)\n\2[ \t]*(?=\n|$)/gi
  let match
  while ((match = pattern.exec(markdown)) !== null) {
    diagrams.push({
      index: diagrams.length,
      source: (match[3] || '').trim(),
    })
  }
  return diagrams
}

function formatMermaidError(error) {
  if (error instanceof Error) {
    return error.message
  }
  if (error && typeof error === 'object') {
    if (typeof error.str === 'string') return error.str
    if (typeof error.message === 'string') return error.message
    try {
      return JSON.stringify(error)
    } catch {
      return String(error)
    }
  }
  return String(error)
}

function serializeHash(error) {
  if (!error || typeof error !== 'object' || !('hash' in error)) return null
  const hash = error.hash
  if (!hash || typeof hash !== 'object') return hash ?? null
  try {
    return JSON.parse(JSON.stringify(hash))
  } catch {
    return String(hash)
  }
}

installDomGlobals()

const markdown = await fs.readFile(inputPath, 'utf8')
const diagrams = extractMermaidDiagrams(markdown)
const { default: mermaid } = await import('mermaid')

mermaid.initialize({
  startOnLoad: false,
  theme: 'neutral',
  securityLevel: 'strict',
  flowchart: {
    useMaxWidth: true,
    htmlLabels: true,
  },
})

const errors = []
for (const diagram of diagrams) {
  try {
    await mermaid.render(`codify-delivery-summary-${Date.now()}-${diagram.index}`, diagram.source)
  } catch (error) {
    errors.push({
      index: diagram.index,
      message: formatMermaidError(error),
      hash: serializeHash(error),
      source: diagram.source,
    })
  }
}

const result = {
  ok: errors.length === 0,
  diagramCount: diagrams.length,
  errors,
}

process.stdout.write(`${JSON.stringify(result, null, 2)}\n`)
