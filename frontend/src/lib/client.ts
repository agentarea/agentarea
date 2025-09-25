import createClient from "openapi-fetch";
import type { paths } from "../api/schema";
import { getAuthTokenClient } from "./auth-client";

// Create the base client
const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || process.env.API_URL || "http://localhost:8000",
});

// Add authentication middleware
client.use({
  async onRequest({ request }) {
    // Get authentication token from current browser session
    try {
      const authToken = await getAuthTokenClient();
      if (authToken) {
        request.headers.set("Authorization", `Bearer ${authToken}`);
      }
    } catch (error: any) {
      console.error("Error getting auth token (client):", error);
      // Continue without Authorization header if authentication fails
      // This allows requests to work even if session is invalid
    }

    // Add workspace header
    // For now, use a default workspace. In a real implementation,
    // this would come from user preferences, URL parameters, or context
    const workspaceId = typeof window !== "undefined"
      ? localStorage.getItem("selectedWorkspace") || "default"
      : "default";

    request.headers.set("X-Workspace-ID", workspaceId);

    return request;
  },
  async onResponse({ response }) {
    // Let the application handle 401 responses
    // No automatic redirects from client level
    return response;
  }
});

export default client;
