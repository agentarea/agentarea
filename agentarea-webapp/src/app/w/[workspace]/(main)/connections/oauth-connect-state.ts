/**
 * What the connection page may offer for authorizing a remote MCP server.
 *
 * The backend preflight (`GET /v1/mcp-oauth/preflight`) answers whether OAuth
 * can start at all and what is missing. Deriving the affordance from that
 * answer — instead of from "is this a URL-type instance" — is what keeps a
 * Connect button from being offered for a provider that has no dynamic client
 * registration and therefore cannot complete without the workspace's own
 * OAuth app.
 */

import type { CustomOAuthAppCredentials } from "@/lib/oauth-app";

export type { CustomOAuthAppCredentials };

export type MCPOAuthPreflight = {
  instance_id: string | null;
  server_id?: string | null;
  status: "ready" | "oauth_app_required" | "unsupported";
  connected: boolean;
  detail: string;
  issuer: string | null;
  authorization_endpoint: string | null;
  scopes: string[];
};

export type OAuthConnectState =
  /** Not an authorizable connection — show nothing. */
  | { kind: "hidden" }
  | { kind: "loading" }
  /** Cannot be authorized this way; `reason` says why. No action offered. */
  | { kind: "unsupported"; reason: string }
  /** Connect can run on its own (the provider supports RFC 7591). */
  | { kind: "ready"; connected: boolean }
  /** Connect needs a client ID/secret first. */
  | {
      kind: "needs_oauth_app";
      connected: boolean;
      reason: string;
      issuer: string | null;
    };

export type AuthorizeRequest = {
  instance_id: string;
  credential_mode: "auto" | "custom";
  return_to?: string;
} & CustomOAuthAppCredentials;

export function deriveOAuthConnectState({
  isUrlType,
  preflight,
  error,
}: {
  isUrlType: boolean;
  preflight: MCPOAuthPreflight | null;
  error?: string | null;
}): OAuthConnectState {
  if (!isUrlType) return { kind: "hidden" };
  if (error) return { kind: "unsupported", reason: error };
  if (!preflight) return { kind: "loading" };

  switch (preflight.status) {
    case "ready":
      return { kind: "ready", connected: preflight.connected };
    case "oauth_app_required":
      return {
        kind: "needs_oauth_app",
        connected: preflight.connected,
        reason: preflight.detail,
        issuer: preflight.issuer,
      };
    case "unsupported":
      return { kind: "unsupported", reason: preflight.detail };
  }
}

/**
 * Build the authorize request, or return null when it would be rejected.
 *
 * The API requires exactly one source per credential (typed in or referenced
 * from a workspace secret). Enforcing that here keeps a half-filled form from
 * being posted just to come back as a validation error.
 */
export function buildAuthorizeRequest({
  instanceId,
  state,
  credentials,
  returnTo,
}: {
  instanceId: string;
  state: OAuthConnectState;
  credentials?: CustomOAuthAppCredentials | null;
  returnTo?: string;
}): AuthorizeRequest | null {
  const fields = authorizeFields(state, credentials);
  if (!fields) return null;
  return {
    instance_id: instanceId,
    ...fields,
    ...(returnTo ? { return_to: returnTo } : {}),
  };
}

/**
 * Whether Connect can run yet. Separate from building the request because the
 * create page answers it before the instance the request names exists.
 */
export function canAuthorize({
  state,
  credentials,
}: {
  state: OAuthConnectState;
  credentials?: CustomOAuthAppCredentials | null;
}): boolean {
  return authorizeFields(state, credentials) !== null;
}

function authorizeFields(
  state: OAuthConnectState,
  credentials: CustomOAuthAppCredentials | null | undefined
): Omit<AuthorizeRequest, "instance_id" | "return_to"> | null {
  if (state.kind === "ready") return { credential_mode: "auto" };

  if (state.kind !== "needs_oauth_app" || !credentials) return null;

  const clientId = credentials.client_id?.trim();
  const clientSecret = credentials.client_secret;
  const hasOneClientId =
    Boolean(clientId) !== Boolean(credentials.client_id_secret_id);
  const hasOneClientSecret =
    Boolean(clientSecret) !== Boolean(credentials.client_secret_secret_id);
  if (!hasOneClientId || !hasOneClientSecret) return null;

  return {
    credential_mode: "custom",
    ...(clientId ? { client_id: clientId } : {}),
    ...(clientSecret ? { client_secret: clientSecret } : {}),
    ...(credentials.client_id_secret_id
      ? { client_id_secret_id: credentials.client_id_secret_id }
      : {}),
    ...(credentials.client_secret_secret_id
      ? { client_secret_secret_id: credentials.client_secret_secret_id }
      : {}),
  };
}

/**
 * A remote MCP server that lists its tools without a token verifies as
 * reachable while no user is authorized — the tool list is real and every
 * tool call 401s. The connection page has to say so rather than let a green
 * "verified, 23 tools" stand in for "connected".
 *
 * Only claimed when the server actually advertises OAuth: plenty of remote MCP
 * servers need no token at all, and telling their users that calls will fail
 * would be the same kind of lie in the other direction.
 */
export function summarizeAuthorization({
  isUrlType,
  verificationStatus,
  connected,
  oauthState,
}: {
  isUrlType: boolean;
  verificationStatus: string | undefined;
  connected: boolean;
  oauthState: OAuthConnectState["kind"] | undefined;
}): { authorized: boolean; reachableButUnauthorized: boolean } {
  const serverAdvertisesOAuth =
    oauthState === "ready" || oauthState === "needs_oauth_app";
  return {
    authorized: connected,
    reachableButUnauthorized:
      isUrlType &&
      !connected &&
      verificationStatus === "succeeded" &&
      serverAdvertisesOAuth,
  };
}
