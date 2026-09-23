import { describe, expect, it } from "vitest";

import {
  buildAuthorizeRequest,
  deriveOAuthConnectState,
  summarizeAuthorization,
  type MCPOAuthPreflight,
} from "./oauth-connect-state";

const INSTANCE_ID = "76216436-01e9-4ebc-a8d5-9023ed773cce";

function preflight(over: Partial<MCPOAuthPreflight> = {}): MCPOAuthPreflight {
  return {
    instance_id: INSTANCE_ID,
    status: "ready",
    connected: false,
    detail: "",
    issuer: "https://accounts.google.com",
    authorization_endpoint: "https://accounts.google.com/o/oauth2/v2/auth",
    scopes: ["https://www.googleapis.com/auth/gmail.modify"],
    ...over,
  };
}

describe("deriveOAuthConnectState", () => {
  it("offers nothing until the preflight answer arrives", () => {
    expect(
      deriveOAuthConnectState({ isUrlType: true, preflight: null })
    ).toEqual({ kind: "loading" });
  });

  it("asks for an OAuth app instead of offering a Connect that cannot finish", () => {
    const state = deriveOAuthConnectState({
      isUrlType: true,
      preflight: preflight({
        status: "oauth_app_required",
        detail: "accounts.google.com does not support Dynamic Client Registration",
      }),
    });

    expect(state).toEqual({
      kind: "needs_oauth_app",
      connected: false,
      reason:
        "accounts.google.com does not support Dynamic Client Registration",
      issuer: "https://accounts.google.com",
    });
  });

  it("carries the reason through when the server cannot be authorized at all", () => {
    const state = deriveOAuthConnectState({
      isUrlType: true,
      preflight: preflight({
        status: "unsupported",
        detail: "Could not fetch OAuth protected-resource metadata",
      }),
    });

    expect(state).toEqual({
      kind: "unsupported",
      reason: "Could not fetch OAuth protected-resource metadata",
    });
  });

  it("treats a preflight that failed to load as unsupported, with the error", () => {
    expect(
      deriveOAuthConnectState({
        isUrlType: true,
        preflight: null,
        error: "Preflight failed: 500",
      })
    ).toEqual({ kind: "unsupported", reason: "Preflight failed: 500" });
  });

  it("stays hidden for container-backed connections", () => {
    expect(
      deriveOAuthConnectState({ isUrlType: false, preflight: preflight() })
    ).toEqual({ kind: "hidden" });
  });
});

describe("buildAuthorizeRequest", () => {
  it("registers dynamically when the provider supports it", () => {
    expect(
      buildAuthorizeRequest({
        instanceId: INSTANCE_ID,
        state: { kind: "ready", connected: false },
        returnTo: "https://app.agentarea.ru",
      })
    ).toEqual({
      instance_id: INSTANCE_ID,
      credential_mode: "auto",
      return_to: "https://app.agentarea.ru",
    });
  });

  const needsApp = {
    kind: "needs_oauth_app",
    connected: false,
    reason: "no DCR",
    issuer: "https://accounts.google.com",
  } as const;

  it("sends typed-in credentials as a custom app", () => {
    expect(
      buildAuthorizeRequest({
        instanceId: INSTANCE_ID,
        state: needsApp,
        credentials: { client_id: "  cid  ", client_secret: "shh" },
      })
    ).toEqual({
      instance_id: INSTANCE_ID,
      credential_mode: "custom",
      client_id: "cid",
      client_secret: "shh", // pragma: allowlist secret
    });
  });

  it("sends workspace secret references without their values", () => {
    const request = buildAuthorizeRequest({
      instanceId: INSTANCE_ID,
      state: needsApp,
      credentials: {
        client_id_secret_id: "secret-1",
        client_secret_secret_id: "secret-2",
      },
    });

    expect(request).toEqual({
      instance_id: INSTANCE_ID,
      credential_mode: "custom",
      client_id_secret_id: "secret-1",
      client_secret_secret_id: "secret-2",
    });
  });

  it("refuses a half-filled form rather than posting a request the API rejects", () => {
    expect(
      buildAuthorizeRequest({
        instanceId: INSTANCE_ID,
        state: needsApp,
        credentials: { client_id: "cid" },
      })
    ).toBeNull();

    expect(
      buildAuthorizeRequest({
        instanceId: INSTANCE_ID,
        state: needsApp,
        credentials: {
          client_id: "cid",
          client_secret: "shh", // pragma: allowlist secret
          client_secret_secret_id: "secret-2",
        },
      })
    ).toBeNull();
  });

  it("has nothing to send while the server cannot be authorized", () => {
    expect(
      buildAuthorizeRequest({
        instanceId: INSTANCE_ID,
        state: { kind: "unsupported", reason: "no oauth" },
        credentials: { client_id: "cid", client_secret: "shh" },
      })
    ).toBeNull();
  });
});

describe("summarizeAuthorization", () => {
  it("flags a verified-but-unauthorized connection", () => {
    // Gmail: tools/list needs no token, so verification succeeds and 23 tools
    // are stored while every tool call would 401.
    expect(
      summarizeAuthorization({
        isUrlType: true,
        verificationStatus: "succeeded",
        connected: false,
        oauthState: "needs_oauth_app",
      })
    ).toEqual({ authorized: false, reachableButUnauthorized: true });
  });

  it("does not flag a connection that holds a token", () => {
    expect(
      summarizeAuthorization({
        isUrlType: true,
        verificationStatus: "succeeded",
        connected: true,
        oauthState: "ready",
      })
    ).toEqual({ authorized: true, reachableButUnauthorized: false });
  });

  it("says nothing about authorization when the server is not reachable", () => {
    expect(
      summarizeAuthorization({
        isUrlType: true,
        verificationStatus: "failed",
        connected: false,
        oauthState: "needs_oauth_app",
      })
    ).toEqual({ authorized: false, reachableButUnauthorized: false });
  });

  it("stays quiet for a server that advertises no OAuth at all", () => {
    // Plenty of remote MCP servers are open; "not authorized" would be a lie.
    expect(
      summarizeAuthorization({
        isUrlType: true,
        verificationStatus: "succeeded",
        connected: false,
        oauthState: "unsupported",
      })
    ).toEqual({ authorized: false, reachableButUnauthorized: false });
  });

  it("stays quiet while the preflight answer is still in flight", () => {
    expect(
      summarizeAuthorization({
        isUrlType: true,
        verificationStatus: "succeeded",
        connected: false,
        oauthState: "loading",
      })
    ).toEqual({ authorized: false, reachableButUnauthorized: false });
  });
});
