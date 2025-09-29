`use server`;

import { Configuration, FrontendApi } from "@ory/kratos-client";
import { cookies } from "next/headers";
import { env } from "@/env";

// Create Kratos client for server-side calls
const kratosConfig = new Configuration({
  basePath: env.ORY_ADMIN_URL,
});
const kratos = new FrontendApi(kratosConfig);

/**
 * Get authentication token from current session
 * Returns JWT token or null if no session
 */
export async function getAuthToken(): Promise<string | null> {
  try {
    const cookieStore = await cookies();
    const sessionCookie = cookieStore.get('ory_kratos_session');

    if (!sessionCookie) {
      return null;
    }

    // Call Kratos to get JWT token
    const sessionResponse = await kratos.toSession({
      cookie: `ory_kratos_session=${sessionCookie.value}`,
      tokenizeAs: 'agentarea_jwt'
    });

    if (sessionResponse.data?.tokenized) {
      // Return the JWT token
      return sessionResponse.data.tokenized;
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
    const sessionCookie = cookieStore.get('ory_kratos_session');

    if (!sessionCookie) {
      return null;
    }

    const sessionResponse = await kratos.toSession({
      cookie: `ory_kratos_session=${sessionCookie.value}`
    });

    if (sessionResponse.data?.identity) {
      return {
        id: sessionResponse.data.identity.id,
        email: sessionResponse.data.identity.traits?.email,
        name: sessionResponse.data.identity.traits?.name?.first
          ? `${sessionResponse.data.identity.traits.name.first} ${sessionResponse.data.identity.traits.name.last || ''}`.trim()
          : sessionResponse.data.identity.traits?.username || sessionResponse.data.identity.traits?.email,
      };
    }

    return null;
  } catch (error: any) {
    console.error("Error getting current user:", error);
    return null;
  }
}