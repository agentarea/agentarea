/**
 * Single source of truth for "is the user authenticated" on the server.
 *
 * The criterion here MUST match what the API depends on: a live Kratos
 * session that can be tokenized as an agentarea JWT (tokenize_as=agentarea_jwt,
 * the same endpoint getAuthToken uses). This keeps the route gate and the API
 * Authorization in lockstep so a dead session cannot produce a "zombie
 * logged-in" shell.
 */

import { KRATOS_WHOAMI_TIMEOUT_MS } from "./server-timeouts";

const PUBLIC_ROUTE_PREFIXES = ["/auth", "/error", "/404", "/500"];

/**
 * True when the pathname falls under a protected route prefix.
 *
 * Every page except the landing and auth/error surfaces belongs to the
 * authenticated app shell. Keeping a public allowlist prevents new `(main)`
 * routes from silently bypassing the tokenization gate.
 */
export function isProtectedRoute(pathname: string): boolean {
  return (
    pathname !== "/" &&
    !PUBLIC_ROUTE_PREFIXES.some(
      (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`)
    )
  );
}

/**
 * Returns true only when the forwarded cookies resolve to a live Kratos
 * session that can be tokenized as an agentarea JWT.
 *
 * The `fetchImpl` parameter exists purely for testability.
 */
export async function hasLiveSession(
  cookieHeader: string | null,
  opts: { orySdkUrl: string; fetchImpl?: typeof fetch }
): Promise<boolean> {
  if (!cookieHeader) {
    return false;
  }

  const doFetch = opts.fetchImpl ?? fetch;

  try {
    const response = await doFetch(
      `${opts.orySdkUrl}/sessions/whoami?tokenize_as=agentarea_jwt`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Cookie: cookieHeader,
        },
        // Bound the middleware gate: this runs before any route renders, so a
        // stalled Kratos here would block the first byte of every page. Fail
        // closed (treat as no session) rather than hang.
        signal: AbortSignal.timeout(KRATOS_WHOAMI_TIMEOUT_MS),
      }
    );

    if (!response.ok) {
      // A dead/expired session is an expected outcome, not an error.
      console.warn("[auth-session] whoami non-ok response:", response.status);
      return false;
    }

    const data = await response.json();
    return Boolean(data?.tokenized);
  } catch (error) {
    console.error(
      "[auth-session] whoami request failed:",
      (error as Error)?.name ?? "unknown"
    );
    return false;
  }
}
