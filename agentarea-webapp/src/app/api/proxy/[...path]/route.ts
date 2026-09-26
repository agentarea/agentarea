import { NextRequest, NextResponse } from "next/server";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";
import { fillWorkspace } from "@/lib/workspace-url";
import { WORKSPACE_QUERY_PARAM } from "@/lib/workspaces";
import { buildProxyResponseHeaders } from "./response-headers";

/**
 * API Proxy Route Handler
 *
 * This route acts as a secure proxy between client-side code and the backend API.
 * It handles authentication by:
 * 1. Extracting auth token from cookies (server-side)
 * 2. Adding Authorization header to backend requests
 * 3. Forwarding requests to the actual backend API
 *
 * Tokens are never exposed to the browser.
 */

async function handleRequest(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> }
) {
  try {
    const { path } = await params;
    const pathString = path.join("/");

    // Get authentication token from cookies (server-side)
    const authToken = await getAuthToken();

    // The browser passes either a concrete path or a
    // `/v1/workspaces/{workspace}/...` template filled from the page it is on.
    const backendUrl = fillWorkspace(
      `${env.API_URL}/${pathString}`,
      resolveRequestWorkspaceSlug(request)
    );

    // Get query parameters from the request
    const { searchParams } = new URL(request.url);
    searchParams.delete(WORKSPACE_QUERY_PARAM);
    const queryString = searchParams.toString();
    const fullUrl = queryString ? `${backendUrl}?${queryString}` : backendUrl;

    // Prepare headers
    const headers = new Headers();
    headers.set("Content-Type", "application/json");
    headers.set("Accept", "application/json");

    // Add authorization header if token is available
    if (authToken) {
      headers.set("Authorization", `Bearer ${authToken}`);
    }

    // Get request body if present
    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      try {
        const requestBody = await request.json();
        body = JSON.stringify(requestBody);
      } catch (_e) {
        // No body or invalid JSON
      }
    }

    // Forward the request to the backend
    const response = await fetch(fullUrl, {
      method: request.method,
      headers,
      body,
    });

    // Non-JSON responses (file streaming, images, PDFs, etc.): forward the
    // body and the safe response headers so the browser can render them.
    // This proxy runs on the webapp's own origin, so Content-Disposition and
    // nosniff are never left to the backend alone — see issue #483.
    const backendContentType = response.headers.get("content-type") || "";
    if (!backendContentType.includes("application/json")) {
      return new NextResponse(response.body, {
        status: response.status,
        headers: buildProxyResponseHeaders({
          contentType: response.headers.get("content-type"),
          contentDisposition: response.headers.get("content-disposition"),
          contentLength: response.headers.get("content-length"),
          etag: response.headers.get("etag"),
          cacheControl: response.headers.get("cache-control"),
          lastModified: response.headers.get("last-modified"),
        }),
      });
    }

    // JSON responses: parse and re-serialize (preserves existing behaviour).
    const responseData = await response.text();
    let jsonData;
    try {
      jsonData = JSON.parse(responseData);
    } catch (_e) {
      jsonData = responseData;
    }

    return NextResponse.json(jsonData, {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error: unknown) {
    console.error("API Proxy Error:", error);
    return NextResponse.json(
      {
        error: "Proxy request failed",
        message: error instanceof Error ? error.message : String(error),
      },
      { status: 500 }
    );
  }
}

// Export handlers for all HTTP methods
export const GET = handleRequest;
export const POST = handleRequest;
export const PUT = handleRequest;
export const PATCH = handleRequest;
export const DELETE = handleRequest;
