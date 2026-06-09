import { vi } from 'vitest'

const localStorageStore = new Map<string, string>()

Object.defineProperty(window, 'localStorage', {
  configurable: true,
  value: {
    getItem: vi.fn((key: string) => localStorageStore.get(key) ?? null),
    setItem: vi.fn((key: string, value: string) => {
      localStorageStore.set(key, String(value))
    }),
    removeItem: vi.fn((key: string) => {
      localStorageStore.delete(key)
    }),
    clear: vi.fn(() => {
      localStorageStore.clear()
    }),
    key: vi.fn((index: number) => Array.from(localStorageStore.keys())[index] ?? null),
    get length() {
      return localStorageStore.size
    },
  },
})

// Mock window.matchMedia
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation(query => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn()
  }))
})

// Mock ResizeObserver
globalThis.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn()
})) as unknown as typeof ResizeObserver

// Mock Element.getBoundingClientRect
Element.prototype.getBoundingClientRect = vi.fn(() => new DOMRect(0, 0, 120, 120))
