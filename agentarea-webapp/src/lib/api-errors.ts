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

export function formatApiError(value: unknown) {
  if (!value) return "Unknown error";
  if (typeof value === "string") return value;
  if (value instanceof Error) return value.message;

  if (typeof value === "object") {
    const record = value as Record<string, unknown>;

    if (record.error) return formatApiError(record.error);

    if (typeof record.detail === "string") return record.detail;
    if (Array.isArray(record.detail)) {
      return record.detail
        .map((item) => {
          if (item && typeof item === "object" && "msg" in item) {
            return String((item as { msg: unknown }).msg);
          }
          return String(item);
        })
        .join(", ");
    }

    if (typeof record.message === "string") return record.message;
  }

  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}
