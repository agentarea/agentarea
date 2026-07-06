import type { CreateClientConfig } from "./client/client";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import { SERVER_API_TIMEOUT_MS } from "@/lib/server-timeouts";

async function addWorkspaceSlug(request: Request) {
  try {
    const { headers } = await import("next/headers");
    const requestHeaders = await headers();
    const workspaceSlug = requestHeaders.get("x-workspace-slug");
    if (workspaceSlug) {
      request.headers.set("X-Workspace-Slug", workspaceSlug);
    }
  } catch {
    // headers() is unavailable outside a request scope (for example build-time
    // prefetch); in that case the backend falls back to the user's personal
    // workspace.
  }
}

async function addAuthToken(request: Request) {
  const url = request.url;
  const method = request.method;

  try {
    const authToken = await getAuthToken();
    if (authToken) {
      request.headers.set("Authorization", `Bearer ${authToken}`);
    } else {
      console.warn(
        `[Server Client] ${method} ${url} - No auth token available`
      );
    }
  } catch (error) {
    console.error(
      `[Server Client] ${method} ${url} - Error getting auth token:`,
      error
    );
  }
}

export const createClientConfig: CreateClientConfig = (config) => ({
  ...config,
  baseUrl: env.API_URL,
  fetch: async (input, init) => {
    const request = new Request(input, {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(SERVER_API_TIMEOUT_MS),
    });

    await addAuthToken(request);
    await addWorkspaceSlug(request);

    const response = await fetch(request);

    if (response.status === 403) {
      console.error("[Server Client] 403 Forbidden details:", {
        url: response.url,
        status: response.status,
        statusText: response.statusText,
      });
      throw new Error(
        `Forbidden: Received a 403 response from the API (${response.url})`
      );
    }

    return response;
  },
});
