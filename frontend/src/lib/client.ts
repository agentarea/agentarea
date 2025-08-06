import createClient from "openapi-fetch";
import type { paths } from "../api/schema";

// Create the base client
const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

// Add authentication middleware
client.use({
  async onRequest({ request }) {
    // Get the JWT token from Clerk
    // For client-side requests, we'll use the Clerk session token
    if (typeof window !== "undefined") {
      try {
        const response = await fetch("/api/auth/token");
        if (response.ok) {
          const { token } = await response.json();
          if (token) {
            request.headers.set("Authorization", `Bearer ${token}`);
          }
        }
      } catch (error) {
        console.error("Error getting auth token:", error);
      }
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
    // Handle 401 responses by redirecting to login
    if (response.status === 401) {
      // Redirect to login page
      if (typeof window !== "undefined") {
        window.location.href = "/sign-in";
      }
    }
    
    return response;
  }
});

export default client;
