import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import {
  ONBOARDING_STORAGE_KEY,
  getOnboardingDismissed,
  setOnboardingDismissed,
  clearOnboardingDismissed,
} from './useOnboarding'

describe('useOnboarding', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('returns false when onboarding has not been dismissed', () => {
    expect(getOnboardingDismissed()).toBe(false)
  })

  it('persists dismissal state to localStorage', () => {
    setOnboardingDismissed(true)
    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('true')
    expect(getOnboardingDismissed()).toBe(true)

    setOnboardingDismissed(false)
    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBe('false')
    expect(getOnboardingDismissed()).toBe(false)
  })

  it('clears dismissal state', () => {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, 'true')

    clearOnboardingDismissed()

    expect(localStorage.getItem(ONBOARDING_STORAGE_KEY)).toBeNull()
    expect(getOnboardingDismissed()).toBe(false)
  })

  it('fails open when storage throws', () => {
    const getItemSpy = vi.spyOn(localStorage, 'getItem').mockImplementation(() => {
      throw new Error('getItem failed')
    })
    const setItemSpy = vi.spyOn(localStorage, 'setItem').mockImplementation(() => {
      throw new Error('setItem failed')
    })
    const removeItemSpy = vi.spyOn(localStorage, 'removeItem').mockImplementation(() => {
      throw new Error('removeItem failed')
    })

    expect(getOnboardingDismissed()).toBe(false)
    expect(() => setOnboardingDismissed(true)).not.toThrow()
    expect(() => setOnboardingDismissed(false)).not.toThrow()
    expect(() => clearOnboardingDismissed()).not.toThrow()

    expect(getItemSpy).toHaveBeenCalled()
    expect(setItemSpy).toHaveBeenCalledTimes(2)
    expect(removeItemSpy).toHaveBeenCalledTimes(1)
  })
})
