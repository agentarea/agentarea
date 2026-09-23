import { NextRequest, NextResponse } from "next/server";
import { env } from "@/env";
import { getAuthToken } from "@/lib/getAuthToken";
import { resolveRequestWorkspaceSlug } from "@/lib/workspace-request";
import { WORKSPACE_REFERENCE_HEADER } from "@/lib/workspaces";

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

    // Construct the backend URL
    const backendUrl = `${env.API_URL}/${pathString}`;

    // Get query parameters from the request
    const { searchParams } = new URL(request.url);
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

    const workspaceSlug = await resolveRequestWorkspaceSlug(request);
    if (workspaceSlug) {
      headers.set(WORKSPACE_REFERENCE_HEADER, workspaceSlug);
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

    // Non-JSON responses (file streaming, images, PDFs, etc.):
    // forward body and Content-Type directly so the browser can render them.
    const backendContentType = response.headers.get("content-type") || "";
    if (!backendContentType.includes("application/json")) {
      return new NextResponse(response.body, {
        status: response.status,
        headers: { "content-type": backendContentType },
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
      { error: "Proxy request failed", message: error instanceof Error ? error.message : String(error) },
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
