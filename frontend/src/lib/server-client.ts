import createClient from "openapi-fetch";
import type { paths } from "../api/schema";
import { getAuthToken } from "./auth";
import { env } from "@/env";
import { cookies } from "next/headers";

// Create the server-side client - uses server-only env vars
const serverClient = createClient<paths>({
  baseUrl: env.API_URL, // Server-only env var, NOT exposed to browser
});

// Add authentication middleware that runs server-side
serverClient.use({
  async onRequest({ request }) {
    // Get authentication token from cookies (server-side)
    // The JWT token already contains workspace_id in its claims, so we don't need to send it separately
    try {
      const authToken = await getAuthToken();
      if (authToken) {
        request.headers.set("Authorization", `Bearer ${authToken}`);
      }
    } catch (error: any) {
      console.error("Error getting auth token (server):", error);
      // Continue without Authorization header if authentication fails
    }

    return request;
  },
  async onResponse({ response }) {
    // Handle responses if needed
    return response;
  }
});

export default serverClient;
