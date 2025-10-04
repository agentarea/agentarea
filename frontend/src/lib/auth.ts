`use server`;

import { Configuration, FrontendApi } from "@ory/kratos-client";
import { cookies } from "next/headers";
import { env } from "@/env";

// Create Kratos client for server-side calls via our proxy
const kratosConfig = new Configuration({
  basePath: env.NEXT_PUBLIC_ORY_SDK_URL,
  apiKey: '', // No API key needed for our proxy
});
const kratos = new FrontendApi(kratosConfig);

/**
 * Get authentication token from current session
 * Returns JWT token or null if no session
 */
export async function getAuthToken(): Promise<string | null> {
  try {
    const cookieStore = await cookies();

    // Get all cookies to forward to Kratos
    const allCookies = cookieStore.getAll();
    const cookieHeader = allCookies
      .map(cookie => `${cookie.name}=${cookie.value}`)
      .join('; ');

    if (!cookieHeader) {
      return null;
    }

    // Call Kratos directly with fetch to get JWT token
    const response = await fetch(`${env.NEXT_PUBLIC_ORY_SDK_URL}/sessions/whoami?tokenize_as=agentarea_jwt`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Cookie': cookieHeader
      }
    });

    if (response.ok) {
      const data = await response.json();
      if (data.tokenized) {
        return data.tokenized;
      }
    }

    return null;
  } catch (error: any) {
    console.error("Error getting JWT token from Kratos:", error);
    // Return null if authentication fails
    // This allows requests to work even if session is invalid
    return null;
  }
}

/**
 * Get current user information from session
 */
export async function getCurrentUser() {
  try {
    const cookieStore = await cookies();

    // Get all cookies to forward to Kratos
    const allCookies = cookieStore.getAll();
    const cookieHeader = allCookies
      .map(cookie => `${cookie.name}=${cookie.value}`)
      .join('; ');

    if (!cookieHeader) {
      return null;
    }

    // Call Kratos directly with fetch
    const response = await fetch(`${env.NEXT_PUBLIC_ORY_SDK_URL}/sessions/whoami`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Cookie': cookieHeader
      }
    });

    if (response.ok) {
      const data = await response.json();
      if (data.identity) {
        return {
          id: data.identity.id,
          email: data.identity.traits?.email,
          name: data.identity.traits?.name?.first
            ? `${data.identity.traits.name.first} ${data.identity.traits.name.last || ''}`.trim()
            : data.identity.traits?.username || data.identity.traits?.email,
        };
      }
    }

    return null;
  } catch (error: any) {
    console.error("Error getting current user:", error);
    return null;
  }
}