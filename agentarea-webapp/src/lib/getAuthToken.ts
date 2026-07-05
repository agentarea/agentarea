"use server";

import { cache } from "react";
import { cookies } from "next/headers";
import { env } from "@/env";
import { KRATOS_WHOAMI_TIMEOUT_MS } from "./server-timeouts";

/**
 * Get authentication token from current session.
 * Returns a freshly tokenized Kratos JWT, or null if there is no live session.
 *
 * Deliberately STATELESS across requests: the JWT is a short-lived token
 * derived from the long-lived Kratos session cookie, so it is re-resolved per
 * request rather than cached in process memory. A cross-request in-memory cache
 * is an anti-pattern here — it does not survive horizontal scaling (each node
 * keeps its own copy, producing non-deterministic staleness), leaks entries
 * that are never evicted, and can pin a stale/null token past its real expiry.
 *
 * De-duplication WITHIN a single server render is handled by React.cache()
 * below, so a page issuing many API calls resolves the session via Kratos
 * `whoami` at most once per request. If `whoami` ever becomes a measured
 * bottleneck, add a SHARED (e.g. Valkey) cache keyed by session id with a TTL
 * bounded by the token's own exp — not a per-process Map.
 */
async function getAuthTokenImpl(): Promise<string | null> {
  try {
    const cookieStore = await cookies();

    // Forward all cookies to Kratos so it can resolve the session
    const allCookies = cookieStore.getAll();
    const cookieHeader = allCookies
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");

    if (!cookieHeader) {
      console.warn("[getAuthToken] No cookies found");
      return null;
    }

    console.debug("[getAuthToken] Calling Kratos whoami endpoint");

    // Call Kratos directly to tokenize the session into an agentarea JWT
    const response = await fetch(
      `${env.ORY_SDK_URL}/sessions/whoami?tokenize_as=agentarea_jwt`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Cookie: cookieHeader,
        },
        // Bound the call so a stalled Kratos fails fast instead of hanging the
        // whole server render (which would never flush a first byte).
        signal: AbortSignal.timeout(KRATOS_WHOAMI_TIMEOUT_MS),
      }
    );

    console.log("[getAuthToken] Kratos response status:", response.status);

    if (response.ok) {
      const data = await response.json();
      if (data.tokenized) {
        console.log("[getAuthToken] JWT token received successfully");
        return data.tokenized;
      }
      console.warn("[getAuthToken] No tokenized field in response");
      return null;
    }

    console.error(
      "[getAuthToken] Kratos response not OK:",
      response.status,
      response.statusText
    );
    return null;
  } catch (error: any) {
    console.error("[getAuthToken] Error getting JWT token from Kratos:", error);
    // Return null if authentication fails; callers treat null as "no session".
    return null;
  }
}

/**
 * Exported with React.cache() for request-scoped de-duplication: multiple calls
 * within the same server render resolve the session only once.
 */
export const getAuthToken = cache(getAuthTokenImpl);
