import { describe, expect, it } from "vitest";
import {
  deriveConnectStep,
  needsOAuthPreflight,
  stepAfterSignInError,
} from "./connect-step";

const KEY = { name: "API_KEY", isSecret: true, isRequired: true };
const TEAM = { name: "X-Team-Token", isSecret: true, isRequired: true };
const base: Parameters<typeof deriveConnectStep>[0] = {
  secretFields: [],
  missingFields: [],
  hasStoredSecrets: false,
  authorized: false,
  oauth: null,
  verificationStatus: "never_attempted",
};
const UNAUTHORIZED = { message: "HTTP 401 Unauthorized" };
// The API's verdict for an upstream 401/403; the message carries no marker.
const REFUSED = {
  code: "upstream_unauthorized",
  message: "SandBase rejected the credentials",
};
const REAUTH = {
  code: "oauth_reauth_required",
  message: "OAuth session expired or was revoked. Reconnect with OAuth.",
};

describe("deriveConnectStep", () => {
  it("asks to replace the key the upstream refused, by the API's code", () => {
    expect(
      deriveConnectStep({
        ...base,
        secretFields: [KEY],
        hasStoredSecrets: true,
        verificationStatus: "failed",
        verificationError: REFUSED,
      })
    ).toEqual({ kind: "needs_key", fields: [KEY], replace: true });
  });

  it("asks a signed-in connection the upstream refused to sign in again, by code", () => {
    expect(
      deriveConnectStep({
        ...base,
        authorized: true,
        verificationStatus: "failed",
        verificationError: REFUSED,
      })
    ).toEqual({ kind: "needs_sign_in", reason: REFUSED.message });
  });

  it("offers sign-in over a missing key when the provider can do OAuth on its own", () => {
    expect(
      deriveConnectStep({
        ...base,
        missingFields: [KEY],
        oauth: { status: "ready", connected: false },
      })
    ).toEqual({ kind: "needs_sign_in" });
  });

  it("asks for the key when OAuth would need the workspace's own app", () => {
    expect(
      deriveConnectStep({
        ...base,
        missingFields: [KEY],
        oauth: { status: "oauth_app_required", connected: false },
      })
    ).toEqual({ kind: "needs_key", fields: [KEY], replace: false });
  });

  it("does not ask for a key once the user has signed in", () => {
    // Back from the provider the instance carries an OAuth credential; the
    // declared header is satisfied by it.
    expect(
      deriveConnectStep({
        ...base,
        missingFields: [KEY],
        authorized: true,
        verificationStatus: "succeeded",
      })
    ).toEqual({ kind: "connected" });
  });

  it("asks a connection whose OAuth session expired to sign in again", () => {
    expect(
      deriveConnectStep({
        ...base,
        authorized: true,
        oauth: { status: "ready", connected: true },
        verificationStatus: "failed",
        verificationError: REAUTH,
      })
    ).toEqual({ kind: "needs_sign_in", reason: REAUTH.message });
  });

  it("asks a signed-in connection the upstream refuses to sign in again", () => {
    expect(
      deriveConnectStep({
        ...base,
        authorized: true,
        verificationStatus: "failed",
        verificationError: { message: "403 Forbidden" },
      })
    ).toEqual({ kind: "needs_sign_in", reason: "403 Forbidden" });
  });

  it("asks to replace every declared key when the upstream refuses the stored one", () => {
    // Nothing is missing, the key is wrong: show all of them, not none.
    expect(
      deriveConnectStep({
        ...base,
        secretFields: [KEY, TEAM],
        hasStoredSecrets: true,
        oauth: { status: "ready", connected: false },
        verificationStatus: "failed",
        verificationError: UNAUTHORIZED,
      })
    ).toEqual({ kind: "needs_key", fields: [KEY, TEAM], replace: true });
  });

  it("does not ask to replace a key for a failure that is not about auth", () => {
    expect(
      deriveConnectStep({
        ...base,
        secretFields: [KEY],
        hasStoredSecrets: true,
        verificationStatus: "failed",
        verificationError: { message: "Connection timed out" },
      })
    ).toEqual({ kind: "failed", message: "Connection timed out" });
  });

  it("asks a verified server that advertises OAuth to sign in anyway", () => {
    // It lists tools without a token, so verification passes while every
    // tool call would 401.
    expect(
      deriveConnectStep({
        ...base,
        oauth: { status: "ready", connected: false },
        verificationStatus: "succeeded",
      })
    ).toEqual({ kind: "needs_sign_in" });
  });

  it("falls back to verification when OAuth is not possible", () => {
    const unsupported = { status: "unsupported", connected: false } as const;
    expect(
      deriveConnectStep({ ...base, oauth: unsupported, verificationStatus: "in_progress" })
    ).toEqual({ kind: "verifying" });
    expect(
      deriveConnectStep({ ...base, oauth: unsupported })
    ).toEqual({ kind: "unverified" });
  });
});

describe("needsOAuthPreflight", () => {
  const remote: Parameters<typeof needsOAuthPreflight>[0] = {
    transport: "url",
    authorized: false,
    hasStoredSecrets: false,
    verificationStatus: "never_attempted",
  };

  it("asks the provider for a remote connection with no credential yet", () => {
    expect(needsOAuthPreflight(remote)).toBe(true);
  });

  it("asks it again when a signed-in connection must sign in again", () => {
    expect(
      needsOAuthPreflight({
        ...remote,
        authorized: true,
        verificationStatus: "failed",
        verificationError: REAUTH,
      })
    ).toBe(true);
  });

  it("asks it again when the upstream refused a signed-in connection", () => {
    expect(
      needsOAuthPreflight({
        ...remote,
        authorized: true,
        verificationStatus: "failed",
        verificationError: REFUSED,
      })
    ).toBe(true);
  });

  it("skips it while the check runs, so polling never reaches the provider", () => {
    expect(needsOAuthPreflight({ ...remote, verificationStatus: "in_progress" })).toBe(false);
  });

  it("skips it when the step cannot be sign-in", () => {
    expect(needsOAuthPreflight({ ...remote, transport: "docker" })).toBe(false);
    expect(needsOAuthPreflight({ ...remote, authorized: true })).toBe(false);
    expect(
      needsOAuthPreflight({
        ...remote,
        hasStoredSecrets: true,
        verificationStatus: "failed",
        verificationError: UNAUTHORIZED,
      })
    ).toBe(false);
  });
});

describe("stepAfterSignInError", () => {
  const SIGN_IN = { kind: "needs_sign_in" } as const;

  it("asks for the key when the provider refused to register AgentArea", () => {
    expect(stepAfterSignInError(SIGN_IN, "oauth_app_required", [KEY])).toEqual(
      { kind: "needs_key", fields: [KEY], replace: false }
    );
  });

  it("keeps sign-in when the connection takes no key to fall back to", () => {
    expect(stepAfterSignInError(SIGN_IN, "oauth_app_required", [])).toBe(
      SIGN_IN
    );
  });

  it("keeps sign-in for any other failure, or none", () => {
    expect(stepAfterSignInError(SIGN_IN, "http_error", [KEY])).toBe(SIGN_IN);
    expect(stepAfterSignInError(SIGN_IN, null, [KEY])).toBe(SIGN_IN);
  });

  it("leaves a step that is not sign-in alone", () => {
    const connected = { kind: "connected" } as const;
    expect(stepAfterSignInError(connected, "oauth_app_required", [KEY])).toBe(
      connected
    );
  });
});
