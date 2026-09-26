import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import { SERVER_API_TIMEOUT_MS } from "@/lib/server-timeouts";
import { fillWorkspace, isWorkspaceScoped } from "@/lib/workspace-url";
import type { CreateClientConfig } from "./client/client";

/**
 * Put the page's workspace into a `/v1/workspaces/{workspace}/...` URL; a
 * workspace-less endpoint goes out as generated. Outside a request scope
 * there is no page, so a workspace-scoped call fails instead of guessing.
 */
async function fillRequestWorkspace(url: string): Promise<string> {
  if (!isWorkspaceScoped(url)) return url;
  // Imported lazily: this module is also pulled into the browser bundle via
  // the generated client, and next/headers cannot be statically imported
  // there.
  const { getRequestWorkspaceSlug } = await import("@/lib/workspace-context");
  return fillWorkspace(url, await getRequestWorkspaceSlug());
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
    if (typeof input !== "string") {
      throw new TypeError("The generated client passes its URL as a string");
    }
    const request = new Request(await fillRequestWorkspace(input), {
      ...init,
      signal: init?.signal ?? AbortSignal.timeout(SERVER_API_TIMEOUT_MS),
    });

    await addAuthToken(request);

    const response = await fetch(request);

    if (response.status === 403) {
      console.error("[Server Client] 403 Forbidden details:", {
        url: response.url,
        status: response.status,
        statusText: response.statusText,
      });
    }

    return response;
  },
});
