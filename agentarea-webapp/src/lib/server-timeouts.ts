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

/**
 * MCP App resource reads and tool calls reach an MCP workload that serverless
 * mode may have reclaimed. The first call after an idle period waits for it to
 * start — an npx server downloads and boots its package — which takes far
 * longer than a plain API read.
 */
export const MCP_APP_TIMEOUT_MS =
  Number(process.env.MCP_APP_TIMEOUT_MS) || 120_000;
