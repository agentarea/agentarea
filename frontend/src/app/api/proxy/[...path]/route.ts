import { getAuthToken } from "@/lib/getAuthToken";
import { env } from "@/env";
import { NextRequest, NextResponse } from "next/server";

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

    // Get request body if present
    let body: string | undefined;
    if (request.method !== "GET" && request.method !== "HEAD") {
      try {
        const requestBody = await request.json();
        body = JSON.stringify(requestBody);
      } catch (e) {
        // No body or invalid JSON
      }
    }

    // Forward the request to the backend
    const response = await fetch(fullUrl, {
      method: request.method,
      headers,
      body,
    });

    // Get response data
    const responseData = await response.text();

    // Parse JSON if possible
    let jsonData;
    try {
      jsonData = JSON.parse(responseData);
    } catch (e) {
      jsonData = responseData;
    }

    // Return the response with the same status code
    return NextResponse.json(jsonData, {
      status: response.status,
      headers: {
        "Content-Type": "application/json",
      },
    });
  } catch (error: any) {
    console.error("API Proxy Error:", error);
    return NextResponse.json(
      { error: "Proxy request failed", message: error.message },
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
