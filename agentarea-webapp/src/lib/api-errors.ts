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
  if (item && typeof item === "object") {
    const record = item as Record<string, unknown>;
    if (typeof record.msg === "string") return record.msg;
    // Any other object shape: `String(item)` here would put the very
    // "[object Object]" this module exists to prevent into the message.
    try {
      return JSON.stringify(item);
    } catch {
      return "";
    }
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
    // FastAPI endpoints may raise HTTPException with a structured detail, e.g.
    // workspace import's `{message, errors, warnings}`. Recurse so the nested
    // `errors` array is read instead of JSON-dumping the whole envelope.
    if (record.detail && typeof record.detail === "object") {
      return formatApiError(record.detail);
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

/**
 * Why a call failed, for under a title that already says what failed: the
 * API's own words when it gave any, else the label with the status.
 */
export function apiErrorDetail(result: ApiResultLike, label: string) {
  const detail = result?.error ? formatApiError(result.error) : "";
  return detail && detail !== "{}" && detail !== "[]"
    ? detail
    : apiErrorMessage(result, label);
}

/** The machine-readable `code` of a problem+json error body, when it has one. */
export function apiErrorCode(result: ApiResultLike): string | null {
  const error = result?.error;
  if (!error || typeof error !== "object") return null;
  const code = (error as Record<string, unknown>).code;
  return typeof code === "string" && code ? code : null;
}

/**
 * Why installing or updating a catalog item was refused (ADR-0044), read from
 * the problem `code` the API sends: the workspace edited the skill, it was not
 * installed from the catalog, its folder no longer matches the pinned tree,
 * the source dropped it, GitHub throttled or could not be reached. A policy
 * refusal is a plain 403 whose detail names the rule. Anything else is an
 * ordinary failure.
 */
export type CatalogFetchFailure =
  | "customized"
  | "notFromCatalog"
  | "moved"
  | "removedUpstream"
  | "rateLimited"
  | "sourceUnreachable"
  | "refusedByPolicy";

const CATALOG_FETCH_CODES: Record<string, CatalogFetchFailure> = {
  skill_customized: "customized",
  skill_not_from_catalog: "notFromCatalog",
  skill_tree_mismatch: "moved",
  skill_source_gone: "removedUpstream",
  github_rate_limited: "rateLimited",
  skill_source_unreachable: "sourceUnreachable",
};

export function catalogFetchFailure(
  result: ApiResultLike
): CatalogFetchFailure | null {
  const code = apiErrorCode(result);
  if (code && CATALOG_FETCH_CODES[code]) return CATALOG_FETCH_CODES[code];
  return getApiStatus(result) === 403 ? "refusedByPolicy" : null;
}
