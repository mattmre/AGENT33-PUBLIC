export const OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY = "agent33:operations-recovery-focus";
export const OPERATIONS_RECOVERY_FOCUS_VALUE = "session-recovery";
export const OPERATIONS_RECOVERY_PANEL_ID = "operations-session-recovery";

function canUseSessionStorage(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

export function requestOperationsRecoveryFocus(): void {
  if (!canUseSessionStorage()) {
    return;
  }

  try {
    window.sessionStorage.setItem(
      OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY,
      OPERATIONS_RECOVERY_FOCUS_VALUE
    );
  } catch {
    // Ignore storage failures and fall back to generic navigation.
  }
}

export function consumeOperationsRecoveryFocusRequest(): boolean {
  if (!canUseSessionStorage()) {
    return false;
  }

  try {
    const shouldFocus =
      window.sessionStorage.getItem(OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY) ===
      OPERATIONS_RECOVERY_FOCUS_VALUE;
    if (shouldFocus) {
      window.sessionStorage.removeItem(OPERATIONS_RECOVERY_FOCUS_STORAGE_KEY);
    }
    return shouldFocus;
  } catch {
    return false;
  }
}

export function openOperationsRecoveryPanel(onOpenOperations: () => void): void {
  requestOperationsRecoveryFocus();
  onOpenOperations();
}
