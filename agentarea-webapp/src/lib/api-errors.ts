export type ApiResultLike<T = unknown> = {
  data?: T | null;
  error?: unknown;
  status?: number;
};

export function getApiStatus(value: unknown): number | undefined {
  if (!value || typeof value !== "object") return undefined;
  const record = value as Record<string, unknown>;
  const status = record.status ?? record.statusCode;

  return typeof status === "number" ? status : undefined;
}

export function isApiNotFound(value: unknown) {
  return getApiStatus(value) === 404;
}

function itemMessage(item: unknown) {
  if (item && typeof item === "object" && "msg" in item) {
    return String((item as { msg: unknown }).msg);
  }
  return String(item);
}

export function formatApiError(value: unknown) {
  if (!value) return "Unknown error";
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;

  if (typeof value === "object") {
    const record = value as Record<string, unknown>;

    if (record.error) return formatApiError(record.error);

    // problem+json validation failures carry field errors under `errors`.
    if (Array.isArray(record.errors) && record.errors.length > 0) {
      const messages = record.errors.map(itemMessage).filter(Boolean);
      if (messages.length > 0) return messages.join(", ");
    }

    if (typeof record.detail === "string") return record.detail;
    if (Array.isArray(record.detail)) {
      return record.detail.map(itemMessage).join(", ");
    }

    if (typeof record.message === "string") return record.message;

    // problem+json without a usable detail: fall back to the title.
    if (typeof record.title === "string") return record.title;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

/**
 * Build a user-facing message from an `{ data, error, status }` API result.
 * Callers must never interpolate `error` directly — it is the parsed response
 * body, so `String(error)` renders "[object Object]" and hides the failure.
 */
export function apiErrorMessage(result: ApiResultLike, label: string) {
  const status = getApiStatus(result);
  const statusText = status ? ` (${status})` : "";
  if (!result?.error) return `${label}${statusText}`;

  // An error body with nothing readable in it (a bare `{}`) adds noise, not
  // information — the status is the only signal worth showing.
  const detail = formatApiError(result.error);
  if (!detail || detail === "{}" || detail === "[]") {
    return `${label}${statusText}`;
  }
  return `${label}${statusText}: ${detail}`;
}
