"use server";

import { env } from "@/env";
import { cookies } from "next/headers";

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
      console.warn("[getAuthToken] No cookies found");
      return null;
    }

    console.log("[getAuthToken] Calling Kratos whoami endpoint");

    // Call Kratos directly with fetch to get JWT token
    const response = await fetch(`${env.ORY_SDK_URL}/sessions/whoami?tokenize_as=agentarea_jwt`, {
      method: 'GET',
      headers: {
        'Accept': 'application/json',
        'Cookie': cookieHeader
      }
    });

    console.log("[getAuthToken] Kratos response status:", response.status);

    if (response.ok) {
      const data = await response.json();
      if (data.tokenized) {
        console.log("[getAuthToken] JWT token received successfully");
        return data.tokenized;
      } else {
        console.warn("[getAuthToken] No tokenized field in response");
      }
    } else {
      console.error("[getAuthToken] Kratos response not OK:", response.status, response.statusText);
    }

    return null;
  } catch (error: any) {
    console.error("[getAuthToken] Error getting JWT token from Kratos:", error);
    // Return null if authentication fails
    // This allows requests to work even if session is invalid
    return null;
  }
}
