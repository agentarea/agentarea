"use server";

import { cache } from "react";
import { cookies } from "next/headers";
import { env } from "@/env";

/**
 * In-memory token cache with TTL
 * Maps cookie hash -> { token, expiresAt }
 */
const tokenCache = new Map<string, { token: string | null; expiresAt: number }>();

// Cache TTL: 5 minutes (JWT tokens typically last longer but we refresh proactively)
const CACHE_TTL_MS = 5 * 60 * 1000;

/**
 * Get authentication token from current session
 * Returns JWT token or null if no session
 *
 * Uses two-level caching:
 * 1. React.cache() for request-level deduplication (same render)
 * 2. In-memory cache for cross-request caching (5 min TTL)
 */
async function getAuthTokenImpl(): Promise<string | null> {
  try {
    const cookieStore = await cookies();

    // Get all cookies to forward to Kratos
    const allCookies = cookieStore.getAll();
    const cookieHeader = allCookies
      .map((cookie) => `${cookie.name}=${cookie.value}`)
      .join("; ");

    if (!cookieHeader) {
      console.warn("[getAuthToken] No cookies found");
      return null;
    }

    // Create a simple hash of the cookie header for cache key
    // (session cookies are typically stable within a session)
    const cacheKey = cookieHeader;

    // Check in-memory cache
    const cached = tokenCache.get(cacheKey);
    if (cached && cached.expiresAt > Date.now()) {
      console.log("[getAuthToken] Using cached token");
      return cached.token;
    }

    console.debug("[getAuthToken] Calling Kratos whoami endpoint");

    // Call Kratos directly with fetch to get JWT token
    const response = await fetch(
      `${env.ORY_SDK_URL}/sessions/whoami?tokenize_as=agentarea_jwt`,
      {
        method: "GET",
        headers: {
          Accept: "application/json",
          Cookie: cookieHeader,
        },
      }
    );

    console.log("[getAuthToken] Kratos response status:", response.status);

    if (response.ok) {
      const data = await response.json();
      if (data.tokenized) {
        console.log("[getAuthToken] JWT token received successfully");
        const token = data.tokenized;

        // Store in cache
        tokenCache.set(cacheKey, {
          token,
          expiresAt: Date.now() + CACHE_TTL_MS,
        });

        return token;
      } else {
        console.warn("[getAuthToken] No tokenized field in response");
      }
    } else {
      console.error(
        "[getAuthToken] Kratos response not OK:",
        response.status,
        response.statusText
      );
    }

    return null;
  } catch (error: any) {
    console.error("[getAuthToken] Error getting JWT token from Kratos:", error);
    // Return null if authentication fails
    // This allows requests to work even if session is invalid
    return null;
  }
}

/**
 * Exported function with React.cache() for request-level deduplication
 * This ensures multiple calls within the same server render only fetch once
 */
export const getAuthToken = cache(getAuthTokenImpl);
