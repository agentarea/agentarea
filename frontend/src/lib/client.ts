import createClient from "openapi-fetch";
import type { paths } from "../api/schema";

// Create the base client
const client = createClient<paths>({
  baseUrl: process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000",
});

// Add authentication middleware
client.use({
  async onRequest({ request }) {
    // Get the JWT token from NextAuth
    // For client-side requests, we'll use the NextAuth session token
    if (typeof window !== "undefined") {
      try {
        const response = await fetch("/api/auth/session");
        if (response.ok) {
          const session = await response.json();
          if (session?.user) {
            // For now, we'll just pass the user ID as a simple token
            // In production, you'd want a proper JWT token
            request.headers.set("Authorization", `Bearer ${session.user.id}`);
          }
        }
      } catch (error) {
        console.error("Error getting auth session:", error);
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
        window.location.href = "/auth/signin";
      }
    }
    
    return response;
  }
});

export default client;
