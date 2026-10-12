/**
 * What a Connect panel may offer for signing in to a connection — a remote MCP
 * server or a catalog API, answered by one preflight
 * (`GET /v1/workspaces/{workspace}/oauth/preflight`).
 *
 * Deriving the affordance from that answer — instead of from "is this a
 * URL-type instance" — is what keeps a Connect button from being offered for a
 * provider that has neither the operator's OAuth app nor dynamic client
 * registration and therefore cannot complete without the workspace's own app.
 */

import type {
  OAuthAuthorizeRequest,
  OAuthPreflightResponse,
} from "@/api/client";
import type { CustomOAuthAppCredentials } from "@/lib/oauth-app";

export type { CustomOAuthAppCredentials };

export type OAuthPreflight = OAuthPreflightResponse;

/** What is being signed in to: an MCP instance, or a catalog API to connect. */
export type OAuthAuthorizeTarget =
  | { instance_id: string }
  | { catalog_item_id: string };

export type OAuthConnectState =
  /** Not an authorizable connection — show nothing. */
  | { kind: "hidden" }
  | { kind: "loading" }
  /** Cannot be authorized this way; `reason` says why. No action offered. */
  | { kind: "unsupported"; reason: string }
  /**
   * Connect runs on its own, with the operator's `platform` app or a client
   * the provider registers `dynamic`ally.
   */
  | {
      kind: "ready";
      connected: boolean;
      credentialSource?: "platform" | "dynamic" | null;
    }
  /**
   * Connect needs a client ID/secret first. `optional`: the person chose their
   * own app over one that would have worked unattended.
   */
  | {
      kind: "needs_oauth_app";
      connected: boolean;
      reason: string;
      issuer: string | null;
      redirectUri?: string;
      optional?: boolean;
    };

export function deriveOAuthConnectState({
  isUrlType,
  preflight,
  error,
  useOwnApp = false,
}: {
  isUrlType: boolean;
  preflight: OAuthPreflight | null;
  error?: string | null;
  /** The person asked to connect with their own OAuth app instead. */
  useOwnApp?: boolean;
}): OAuthConnectState {
  if (!isUrlType) return { kind: "hidden" };
  if (error) return { kind: "unsupported", reason: error };
  if (!preflight) return { kind: "loading" };

  switch (preflight.status) {
    case "ready":
      if (useOwnApp && canUseOwnApp(preflight)) {
        return {
          kind: "needs_oauth_app",
          connected: preflight.connected,
          reason: "",
          issuer: preflight.issuer ?? null,
          redirectUri: preflight.redirect_uri,
          optional: true,
        };
      }
      return {
        kind: "ready",
        connected: preflight.connected,
        credentialSource: preflight.credential_source ?? null,
      };
    case "oauth_app_required":
      return {
        kind: "needs_oauth_app",
        connected: preflight.connected,
        reason: preflight.detail ?? "",
        issuer: preflight.issuer ?? null,
        redirectUri: preflight.redirect_uri,
      };
    case "unsupported":
      return { kind: "unsupported", reason: preflight.detail ?? "" };
  }
}

/** A rejected registration supersedes discovery, including server-provided preflight. */
export function preflightAfterAuthorizeError(
  preflight: OAuthPreflight | null,
  code: string | null | undefined,
  detail: string
): OAuthPreflight | null {
  if (!preflight || code !== "oauth_app_required") return preflight;
  return { ...preflight, status: "oauth_app_required", detail };
}

/**
 * Whether a ready connection may instead use the person's own OAuth app: only
 * over the operator's app, whose consent screen names AgentArea, not them.
 */
export function canUseOwnApp(preflight: OAuthPreflight | null): boolean {
  return (
    preflight?.status === "ready" && preflight.credential_source === "platform"
  );
}

/**
 * Build the authorize request, or return null when it would be rejected.
 *
 * The API requires exactly one source per credential (typed in or referenced
 * from a workspace secret). Enforcing that here keeps a half-filled form from
 * being posted just to come back as a validation error.
 */
export function buildAuthorizeRequest({
  target,
  state,
  credentials,
  returnTo,
}: {
  target: OAuthAuthorizeTarget;
  state: OAuthConnectState;
  credentials?: CustomOAuthAppCredentials | null;
  returnTo?: string;
}): OAuthAuthorizeRequest | null {
  const fields = credentialFields(state, credentials);
  if (!fields) return null;
  return {
    ...target,
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
  return credentialFields(state, credentials) !== null;
}

function credentialFields(
  state: OAuthConnectState,
  credentials: CustomOAuthAppCredentials | null | undefined
): Pick<
  OAuthAuthorizeRequest,
  | "credential_mode"
  | "client_id"
  | "client_secret"
  | "client_id_secret_id"
  | "client_secret_secret_id"
> | null {
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
