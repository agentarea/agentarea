import { describe, expect, it } from "vitest";
import {
  authorizeTargetOf,
  buildAuthorizeRequest,
  canAuthorize,
  canUseOwnApp,
  clientIdTail,
  deriveOAuthConnectState,
  preflightAfterAuthorizeError,
  preflightTargetOf,
  scopeChoice,
  scopeShortName,
  summarizeAuthorization,
  type OAuthPreflight,
} from "./oauth-connect-state";

const INSTANCE_ID = "76216436-01e9-4ebc-a8d5-9023ed773cce";
const ITEM_ID = "0b5a3e0e-7d0a-4a43-9c64-0d1f6f3e9b11";
const REDIRECT_URI = "https://api.agentarea.ru/v1/oauth/callback";

function preflight(over: Partial<OAuthPreflight> = {}): OAuthPreflight {
  return {
    status: "ready",
    credential_source: "dynamic",
    redirect_uri: REDIRECT_URI,
    connected: false,
    detail: "",
    issuer: "https://accounts.google.com",
    authorization_endpoint: "https://accounts.google.com/o/oauth2/v2/auth",
    scopes: ["https://www.googleapis.com/auth/gmail.modify"],
    ...over,
  };
}

describe("deriveOAuthConnectState", () => {
  it("replaces advertised readiness after registration is refused and preserves app retry settings", () => {
    const before = preflight({
      redirect_uri: "https://app.example.com/callback",
    });
    const after = preflightAfterAuthorizeError(
      before,
      "oauth_app_required",
      "Registration refused"
    );
    const state = deriveOAuthConnectState({
      isUrlType: true,
      preflight: after,
    });
    expect(state).toEqual({
      kind: "needs_oauth_app",
      connected: false,
      reason: "Registration refused",
      issuer: before.issuer,
      redirectUri: before.redirect_uri,
    });
    expect(
      buildAuthorizeRequest({ target: { instance_id: INSTANCE_ID }, state })
    ).toBeNull();
    expect(
      buildAuthorizeRequest({
        target: { instance_id: INSTANCE_ID },
        state,
        credentials: { client_id: "app", client_secret: "secret" },
      })
    ).toMatchObject({ credential_mode: "custom", client_id: "app" });
    expect(preflightAfterAuthorizeError(after, null, "Network failure")).toBe(
      after
    );
  });
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
        detail:
          "accounts.google.com does not support Dynamic Client Registration",
      }),
    });

    expect(state).toEqual({
      kind: "needs_oauth_app",
      connected: false,
      reason:
        "accounts.google.com does not support Dynamic Client Registration",
      issuer: "https://accounts.google.com",
      redirectUri: REDIRECT_URI,
    });
  });

  it("names the client a ready connection signs in with", () => {
    expect(
      deriveOAuthConnectState({
        isUrlType: true,
        preflight: preflight({ credential_source: "platform" }),
      })
    ).toEqual({
      kind: "ready",
      connected: false,
      credentialSource: "platform",
    });
  });

  it("asks for the person's own app when they choose it over the platform app", () => {
    expect(
      deriveOAuthConnectState({
        isUrlType: true,
        preflight: preflight({ credential_source: "platform" }),
        useOwnApp: true,
      })
    ).toEqual({
      kind: "needs_oauth_app",
      connected: false,
      reason: "",
      issuer: "https://accounts.google.com",
      redirectUri: REDIRECT_URI,
      optional: true,
    });
  });

  it("keeps a dynamically registered connection on its own client", () => {
    const ready = preflight({ credential_source: "dynamic" });

    expect(canUseOwnApp(ready)).toBe(false);
    expect(
      deriveOAuthConnectState({
        isUrlType: true,
        preflight: ready,
        useOwnApp: true,
      })
    ).toEqual({ kind: "ready", connected: false, credentialSource: "dynamic" });
  });

  it("reconnects with the connection's own app instead of asking for it again", () => {
    const ready = preflight({
      credential_source: "custom",
      client_id: "1234-own-client-abcd",
      connected: true,
    });
    const state = deriveOAuthConnectState({
      isUrlType: true,
      preflight: ready,
    });

    expect(state).toEqual({
      kind: "ready",
      connected: true,
      credentialSource: "custom",
      clientId: "1234-own-client-abcd",
    });
    expect(
      buildAuthorizeRequest({
        target: { instance_id: INSTANCE_ID },
        state,
        scopes: ["https://www.googleapis.com/auth/gmail.modify"],
      })
    ).toEqual({
      instance_id: INSTANCE_ID,
      credential_mode: "auto",
      scopes: ["https://www.googleapis.com/auth/gmail.modify"],
    });
  });

  it("asks for a new app when the person replaces the connection's own", () => {
    const ready = preflight({ credential_source: "custom", connected: true });

    expect(canUseOwnApp(ready)).toBe(true);
    expect(
      deriveOAuthConnectState({
        isUrlType: true,
        preflight: ready,
        useOwnApp: true,
      })
    ).toEqual({
      kind: "needs_oauth_app",
      connected: true,
      reason: "",
      issuer: "https://accounts.google.com",
      redirectUri: REDIRECT_URI,
      optional: true,
      replacesOwnApp: true,
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
        target: { instance_id: INSTANCE_ID },
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
        target: { instance_id: INSTANCE_ID },
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
      target: { instance_id: INSTANCE_ID },
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
        target: { instance_id: INSTANCE_ID },
        state: needsApp,
        credentials: { client_id: "cid" },
      })
    ).toBeNull();

    expect(
      buildAuthorizeRequest({
        target: { instance_id: INSTANCE_ID },
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
        target: { instance_id: INSTANCE_ID },
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

describe("canAuthorize", () => {
  const needsApp = {
    kind: "needs_oauth_app",
    connected: false,
    reason: "no DCR",
    issuer: "https://accounts.google.com",
  } as const;

  it("is ready without credentials when the provider registers us itself", () => {
    expect(canAuthorize({ state: { kind: "ready", connected: false } })).toBe(
      true
    );
  });

  it("waits for a complete OAuth app before the connection even exists", () => {
    // The create page asks this before it creates the instance the request
    // will name, so readiness cannot depend on having an instance id.
    expect(
      canAuthorize({ state: needsApp, credentials: { client_id: "cid" } })
    ).toBe(false);
    expect(
      canAuthorize({
        state: needsApp,
        credentials: { client_id: "cid", client_secret: "shh" },
      })
    ).toBe(true);
  });
});

describe("catalog APIs", () => {
  const needsApp = {
    kind: "needs_oauth_app",
    connected: false,
    reason: "No AgentArea OAuth app for Yandex Metrica",
    issuer: null,
    redirectUri: REDIRECT_URI,
  } as const;

  it("connects through the same request as an MCP instance", () => {
    expect(
      buildAuthorizeRequest({
        target: { catalog_item_id: ITEM_ID },
        state: {
          kind: "ready",
          connected: false,
          credentialSource: "platform",
        },
        returnTo: "https://app.agentarea.ru",
      })
    ).toEqual({
      catalog_item_id: ITEM_ID,
      credential_mode: "auto",
      return_to: "https://app.agentarea.ru",
    });
  });

  it("sends the user's own app under the same one-source-per-credential rule", () => {
    expect(
      buildAuthorizeRequest({
        target: { catalog_item_id: ITEM_ID },
        state: needsApp,
        credentials: {
          client_id: " cid ",
          client_secret_secret_id: "secret-2",
        },
      })
    ).toEqual({
      catalog_item_id: ITEM_ID,
      credential_mode: "custom",
      client_id: "cid",
      client_secret_secret_id: "secret-2",
    });
    expect(
      buildAuthorizeRequest({
        target: { catalog_item_id: ITEM_ID },
        state: needsApp,
        credentials: {
          client_id: "cid",
          client_id_secret_id: "secret-1",
          client_secret: "shh", // pragma: allowlist secret
        },
      })
    ).toBeNull();
  });
});

const GMAIL_READONLY = "https://www.googleapis.com/auth/gmail.readonly";
const GMAIL_MODIFY = "https://www.googleapis.com/auth/gmail.modify";
const GMAIL_ALL = "https://mail.google.com/";

describe("scopeChoice", () => {
  it("offers nothing to pick when the server lists one scope or none", () => {
    expect(scopeChoice(preflight({ scopes: [GMAIL_MODIFY] }))).toBeNull();
    expect(scopeChoice(preflight({ scopes: [] }))).toBeNull();
    expect(scopeChoice(null)).toBeNull();
  });

  it("offers every scope and starts from the ones the API asks for by default", () => {
    const choice = scopeChoice(
      preflight({
        scopes: [GMAIL_READONLY, GMAIL_MODIFY, GMAIL_ALL],
        default_scopes: [GMAIL_MODIFY],
      })
    );

    expect(choice).toEqual({
      offered: [GMAIL_READONLY, GMAIL_MODIFY, GMAIL_ALL],
      initial: [GMAIL_MODIFY],
    });
  });

  it("starts from everything when the API names no default", () => {
    const choice = scopeChoice(
      preflight({ scopes: [GMAIL_READONLY, GMAIL_MODIFY], default_scopes: [] })
    );

    expect(choice?.initial).toEqual([GMAIL_READONLY, GMAIL_MODIFY]);
  });

  it("has nothing to offer while the server cannot be authorized", () => {
    expect(
      scopeChoice(
        preflight({
          status: "unsupported",
          scopes: [GMAIL_READONLY, GMAIL_MODIFY],
        })
      )
    ).toBeNull();
  });
});

describe("scopeShortName", () => {
  it("keeps the last path segment of a URL scope and leaves others alone", () => {
    expect(scopeShortName(GMAIL_MODIFY)).toBe("gmail.modify");
    expect(scopeShortName(GMAIL_ALL)).toBe("mail.google.com");
    expect(scopeShortName("read:org")).toBe("read:org");
  });
});

describe("picked scopes", () => {
  const state = deriveOAuthConnectState({
    isUrlType: true,
    preflight: preflight(),
  });

  it("are sent with the authorize request", () => {
    const request = buildAuthorizeRequest({
      target: { instance_id: INSTANCE_ID },
      state,
      scopes: [GMAIL_READONLY],
    });

    expect(request?.scopes).toEqual([GMAIL_READONLY]);
  });

  it("leave the API's default in charge when nothing was offered to pick", () => {
    const request = buildAuthorizeRequest({
      target: { instance_id: INSTANCE_ID },
      state,
    });

    expect(request).not.toHaveProperty("scopes");
  });

  it("block Connect when every scope was unticked", () => {
    expect(canAuthorize({ state, scopes: [] })).toBe(false);
    expect(
      buildAuthorizeRequest({
        target: { instance_id: INSTANCE_ID },
        state,
        scopes: [],
      })
    ).toBeNull();
  });
});

describe("clientIdTail", () => {
  it("shows only the end of a client ID", () => {
    expect(clientIdTail("1234-own-client-abcd")).toBe("…abcd");
    expect(clientIdTail("abcd")).toBe("abcd");
  });
});

describe("preflightTargetOf", () => {
  it("names each connection the way the API asks about it", () => {
    expect(preflightTargetOf("instance", INSTANCE_ID)).toEqual({
      instance_id: INSTANCE_ID,
    });
    expect(preflightTargetOf("spec", ITEM_ID)).toEqual({ server_id: ITEM_ID });
    expect(preflightTargetOf("catalog", ITEM_ID)).toEqual({
      catalog_item_id: ITEM_ID,
    });
    expect(preflightTargetOf("api_connection", ITEM_ID)).toEqual({
      openapi_connection_id: ITEM_ID,
    });
  });

  it("signs an existing API connection in again, not a new one", () => {
    expect(
      buildAuthorizeRequest({
        target: authorizeTargetOf("api_connection", ITEM_ID),
        state: { kind: "ready", connected: true, credentialSource: "platform" },
      })
    ).toEqual({ openapi_connection_id: ITEM_ID, credential_mode: "auto" });
  });
});
