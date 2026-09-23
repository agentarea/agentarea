/**
 * Values that the event projection deliberately replaced with a marker. These
 * checks are whole-value only: a real sentence mentioning an event-log marker
 * remains visible.
 */
const TOOL_EVENT_MARKER_PATTERNS = [
  /^\[omitted from event log: \d+ units\]$/,
  /^\[nested value omitted from event log\]$/,
  /^\[[A-Za-z_][A-Za-z0-9_.-]* omitted from event log\]$/,
  /^\[truncated \d+ characters from event log\]$/,
  /^\[redacted\]$/,
];

export const TOOL_DETAILS_UNAVAILABLE = "Full details weren’t saved for this run.";

export function isUnavailableToolValue(value: unknown): boolean {
  return (
    typeof value === "string" &&
    TOOL_EVENT_MARKER_PATTERNS.some((pattern) => pattern.test(value))
  );
}

export function containsUnavailableToolValue(value: unknown): boolean {
  if (isUnavailableToolValue(value)) return true;
  if (Array.isArray(value)) return value.some(containsUnavailableToolValue);
  if (value && typeof value === "object") {
    return Object.values(value as Record<string, unknown>).some(
      containsUnavailableToolValue
    );
  }
  return false;
}

/** Remove only exact sanitizer markers, including markers nested in objects. */
export function stripUnavailableToolValues(value: unknown): unknown {
  if (isUnavailableToolValue(value)) return undefined;
  if (Array.isArray(value)) {
    const items = value
      .map(stripUnavailableToolValues)
      .filter((item): item is unknown => item !== undefined);
    return value.length === 0 || items.length > 0 ? items : undefined;
  }
  if (value && typeof value === "object") {
    const sourceEntries = Object.entries(value as Record<string, unknown>);
    const entries = sourceEntries
      .map(([key, item]) => [key, stripUnavailableToolValues(item)] as const)
      .filter((entry): entry is readonly [string, unknown] => entry[1] !== undefined);
    return sourceEntries.length === 0 || entries.length > 0
      ? Object.fromEntries(entries)
      : undefined;
  }
  return value;
}

/** Whether a value contains any content that is safe to present. */
export function hasAvailableToolValue(value: unknown, nested = false): boolean {
  if (isUnavailableToolValue(value) || value === undefined) {
    return false;
  }
  if (value === null) return nested;
  if (Array.isArray(value)) {
    return (
      value.length === 0 ||
      value.some((item) => hasAvailableToolValue(item, true))
    );
  }
  if (typeof value === "object") {
    const values = Object.values(value as Record<string, unknown>);
    return (
      values.length === 0 ||
      values.some((item) => hasAvailableToolValue(item, true))
    );
  }
  return true;
}
