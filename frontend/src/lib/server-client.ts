import 'server-only';

import createClient from "openapi-fetch";
import type { paths } from "../api/schema";
import { getAuthToken } from "./getAuthToken";
import { env } from "@/env";

// Lazy-initialized server client to prevent env.API_URL access during module load
let serverClient: ReturnType<typeof createClient<paths>> | null = null;

export function getServerClient() {
  if (!serverClient) {
    // Create the server-side client - uses server-only env vars
    serverClient = createClient<paths>({
      baseUrl: env.API_URL, // Server-only env var, NOT exposed to browser
    });

    // Add authentication middleware that runs server-side
    serverClient.use({
      async onRequest({ request }) {
        const url = request.url;
        const method = request.method;

        // Get authentication token from cookies (server-side)
        try {
          const authToken = await getAuthToken();
          if (authToken) {
            request.headers.set("Authorization", `Bearer ${authToken}`);
            console.log(`[Server Client] ${method} ${url} - Auth token added`);
          } else {
            console.warn(`[Server Client] ${method} ${url} - No auth token available`);
          }
        } catch (error: any) {
          console.error(`[Server Client] ${method} ${url} - Error getting auth token:`, error);
          // Continue without Authorization header if authentication fails
        }

        return request;
      },
      async onResponse({ response }) {
        const url = response.url;
        const status = response.status;

        console.log(`[Server Client] Response: ${status} ${url}`);

        if (response.status === 403) {
          console.error("[Server Client] 403 Forbidden details:", {
            url,
            status: response.status,
            statusText: response.statusText
          });
          throw new Error(`Forbidden: Received a 403 response from the API (${url})`);
        }
        return response;
      }
    });
  }

  return serverClient;
}
