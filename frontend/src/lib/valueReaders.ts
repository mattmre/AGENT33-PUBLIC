export function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

export function readString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function readNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

export function readStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

export function extractResultMessage(payload: unknown, fallback: string): string {
  const data = asRecord(payload);
  const directMessage =
    readString(data.message) ||
    readString(data.detail) ||
    readString(data.error) ||
    readString(data.status);

  if (directMessage) {
    return directMessage;
  }

  const errors = readStringArray(data.validation_errors);
  return errors.length > 0 ? errors.join(" ") : fallback;
}
