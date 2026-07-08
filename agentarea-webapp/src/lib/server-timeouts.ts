/**
 * Timeouts for server-side outbound fetches.
 *
 * Next's `fetch` has no default timeout. Without one, a slow or unresponsive
 * upstream (Kratos `whoami` tokenization or the backend API) stalls the whole
 * server render — and, for the middleware whoami, the entire response — with no
 * first byte. These bounds make a stalled upstream fail fast (AbortError) so the
 * page degrades into an error/empty state instead of hanging indefinitely.
 *
 * Overridable via env for ops tuning; defaults are deliberately conservative.
 */
export const KRATOS_WHOAMI_TIMEOUT_MS =
  Number(process.env.KRATOS_WHOAMI_TIMEOUT_MS) || 5000;

export const SERVER_API_TIMEOUT_MS =
  Number(process.env.SERVER_API_TIMEOUT_MS) || 8000;
