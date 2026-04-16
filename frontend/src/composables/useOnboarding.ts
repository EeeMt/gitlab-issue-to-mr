export const ONBOARDING_STORAGE_KEY = 'codify-onboarding-dismissed'

export function getOnboardingDismissed(): boolean {
  try {
    return localStorage.getItem(ONBOARDING_STORAGE_KEY) === 'true'
  } catch {
    return false
  }
}

export function setOnboardingDismissed(dismissed: boolean): void {
  try {
    localStorage.setItem(ONBOARDING_STORAGE_KEY, String(dismissed))
  } catch {
    // Fail open when storage is unavailable.
  }
}

export function clearOnboardingDismissed(): void {
  try {
    localStorage.removeItem(ONBOARDING_STORAGE_KEY)
  } catch {
    // Fail open when storage is unavailable.
  }
}
