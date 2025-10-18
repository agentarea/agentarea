import createClient from "openapi-fetch";
import type { paths } from "../api/schema";

/**
 * Browser-side API Client
 *
 * This client is used in client components (marked with "use client").
 * It makes requests to our Next.js API proxy (/api/proxy/*) which handles
 * authentication server-side, ensuring tokens are never exposed to the browser.
 *
 * The proxy route automatically:
 * - Extracts auth tokens from cookies (server-side)
 * - Adds Authorization headers
 * - Forwards requests to the backend API
 *
 * Usage in client components:
 *   import { listAgents, createAgent } from "@/lib/browser-api";
 */

// Create the browser-side client - points to our Next.js API proxy
const browserClient = createClient<paths>({
  baseUrl: "/api/proxy", // Proxy route handles auth and forwarding
});

// No authentication middleware needed - the proxy handles it server-side
browserClient.use({
  async onRequest({ request }) {
    // All requests go through our secure proxy
    return request;
  },
  async onResponse({ response }) {
    if (response.status === 403) {
      console.error("Forbidden: Received a 403 response from the API");
    }
    return response;
  },
});

export default browserClient;
