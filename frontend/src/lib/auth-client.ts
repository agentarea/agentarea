// Client-only helper to obtain a short-lived JWT from Ory Kratos using the
// current browser session cookie. We call the public whoami endpoint with
// `tokenize_as` so Kratos returns a tokenized JWT for downstream APIs.
export async function getAuthTokenClient(): Promise<string | null> {
  try {
    const base =
      process.env.NEXT_PUBLIC_ORY_PUBLIC_URL ||
      process.env.NEXT_PUBLIC_ORY_URL ||
      "http://localhost:4433"; // Kratos public port by default

    // Ensure no trailing slash
    const baseUrl = base.replace(/\/$/, "");

    const res = await fetch(
      `${baseUrl}/sessions/whoami?tokenize_as=agentarea_jwt`,
      {
        // Include cookies for cross-origin if CORS allows it and the cookie is not HttpOnly SameSite=Strict blocking this context
        credentials: "include",
        headers: {
          Accept: "application/json",
        },
      }
    );

    if (!res.ok) {
      return null;
    }

    const data = await res.json();
    if (data && typeof data === "object" && "tokenized" in data && data.tokenized) {
      return data.tokenized as string;
    }

    return null;
  } catch (err) {
    // Swallow errors and return null to avoid breaking client-side calls
    console.error("auth-client: failed to get JWT from Kratos", err);
    return null;
  }
}