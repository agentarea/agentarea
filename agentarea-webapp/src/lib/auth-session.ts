/**
 * Single source of truth for "is the user authenticated" on the server.
 *
 * The criterion here MUST match what the API depends on: a live Kratos
 * session that can be tokenized as an agentarea JWT (tokenize_as=agentarea_jwt,
 * the same endpoint getAuthToken uses). This keeps the route gate and the API
 * Authorization in lockstep so a dead session cannot produce a "zombie
 * logged-in" shell.
 */

/**
 * Route prefixes that require an authenticated session.
 *
 * This is the single source of truth shared by the middleware gate
 * (src/proxy.ts) and the client shell (ConditionalLayout.tsx).
 */
export const PROTECTED_ROUTE_PREFIXES: string[] = [
  "/workplace",
  "/agents",
  "/tasks",
  "/mcp-servers",
  "/settings",
  "/admin",
  "/skills",
  "/triggers",
  "/inbox",
  "/projects",
  "/network",
];

/**
 * True when the pathname falls under a protected route prefix.
 *
 * Semantics are identical to the original
 * `PROTECTED_ROUTES.some(r => pathname.startsWith(r))`: a prefix match.
 * Note this means "/agentsfoo" matches "/agents" (startsWith), which preserves
 * the prior behavior exactly.
 */
export function isProtectedRoute(pathname: string): boolean {
  return PROTECTED_ROUTE_PREFIXES.some(
    (prefix) =>
      pathname === prefix ||
      pathname.startsWith(`${prefix}/`) ||
      pathname.startsWith(prefix)
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
      }
    );

    if (!response.ok) {
      // A dead/expired session is an expected outcome, not an error.
      console.warn(
        "[auth-session] whoami non-ok response:",
        response.status
      );
      return false;
    }

    const data = await response.json();
    return Boolean(data?.tokenized);
  } catch (error) {
    console.error("[auth-session] whoami request failed:", (error as Error)?.name ?? "unknown");
    return false;
  }
}
