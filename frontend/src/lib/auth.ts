"use server";

import { cookies } from "next/headers";
import { env } from "@/env";

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
    const response = await fetch(`${env.ORY_SDK_URL}/sessions/whoami`, {
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