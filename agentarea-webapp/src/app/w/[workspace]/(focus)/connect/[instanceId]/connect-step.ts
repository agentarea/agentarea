/**
 * The one thing a connect link asks of the person who opens it.
 *
 * An agent created the connection and chose everything else; the page only
 * finishes it: sign in, paste the missing key, or wait for the check.
 */

import type { McpTransport } from "@/api/client/types.gen";
import type { CredentialFieldSpec } from "@/app/w/[workspace]/(main)/connections/credential-fields";
import type { MCPOAuthPreflight } from "@/app/w/[workspace]/(main)/connections/oauth-connect-state";
import type { MCPVerificationStatus } from "@/app/w/[workspace]/(main)/connections/utils";

export type ConnectStep =
  /** `reason`: why a connection that was signed in must sign in again. */
  | { kind: "needs_sign_in"; reason?: string | null }
  /** `replace`: the stored key was refused, so every key is asked for again. */
  | { kind: "needs_key"; fields: CredentialFieldSpec[]; replace: boolean }
  | { kind: "verifying" }
  | { kind: "unverified" }
  | { kind: "connected" }
  | { kind: "failed"; message: string | null };

export type VerificationError = {
  code?: string | null;
  message?: string | null;
} | null;

type Verification = {
  verificationStatus: MCPVerificationStatus;
  verificationError?: VerificationError;
};

/** Verification codes the API records when the upstream refused the credential. */
const AUTH_FAILURE_CODES = ["upstream_unauthorized", "oauth_reauth_required"];

/**
 * The API's `_is_auth_error_payload`: a failed check the upstream refused. The
 * message is matched only for a transport that does not report the status.
 */
function isAuthFailure({
  verificationStatus,
  verificationError,
}: Verification) {
  if (verificationStatus !== "failed") return false;
  const code = verificationError?.code;
  if (code && AUTH_FAILURE_CODES.includes(code)) return true;
  const message = verificationError?.message;
  if (typeof message !== "string") return false;
  return ["401", "403", "Unauthorized", "Forbidden"].some((marker) =>
    message.includes(marker)
  );
}

/** The OAuth credential the connection holds no longer works. */
function mustSignInAgain(verification: Verification, authorized: boolean) {
  return (
    verification.verificationStatus === "failed" &&
    (verification.verificationError?.code === "oauth_reauth_required" ||
      (authorized && isAuthFailure(verification)))
  );
}

/**
 * Whether the page asks the provider how it authorizes. Only when the step
 * can be sign-in, and never while a check runs: that page refreshes every
 * two seconds.
 */
export function needsOAuthPreflight({
  transport,
  authorized,
  hasStoredSecrets,
  ...verification
}: Verification & {
  transport: McpTransport;
  authorized: boolean;
  hasStoredSecrets: boolean;
}): boolean {
  if (
    transport !== "url" ||
    verification.verificationStatus === "in_progress"
  ) {
    return false;
  }
  if (mustSignInAgain(verification, authorized)) return true;
  return !authorized && !hasStoredSecrets;
}

export function deriveConnectStep({
  secretFields,
  missingFields,
  hasStoredSecrets,
  authorized,
  oauth,
  ...verification
}: Verification & {
  /** Required secret fields the connection declares. */
  secretFields: CredentialFieldSpec[];
  /** Required secret fields with no value yet. */
  missingFields: CredentialFieldSpec[];
  /** The connection already holds a secret (a key was given). */
  hasStoredSecrets: boolean;
  /** An OAuth credential is attached to the connection. */
  authorized: boolean;
  /** The OAuth preflight; null when it does not apply or was not answered. */
  oauth: Pick<MCPOAuthPreflight, "status" | "connected"> | null;
}): ConnectStep {
  if (mustSignInAgain(verification, authorized)) {
    return {
      kind: "needs_sign_in",
      reason: verification.verificationError?.message ?? null,
    };
  }

  const signedIn = authorized || oauth?.connected === true;
  if (!signedIn) {
    const offersOAuth = !hasStoredSecrets && oauth !== null;
    // One sign-in beats pasting a key the provider would have issued anyway.
    if (offersOAuth && oauth.status === "ready")
      return { kind: "needs_sign_in" };
    if (missingFields.length > 0) {
      return { kind: "needs_key", fields: missingFields, replace: false };
    }
    if (offersOAuth && oauth.status === "oauth_app_required") {
      return { kind: "needs_sign_in" };
    }
    if (
      hasStoredSecrets &&
      secretFields.length > 0 &&
      isAuthFailure(verification)
    ) {
      return { kind: "needs_key", fields: secretFields, replace: true };
    }
  }

  switch (verification.verificationStatus) {
    case "succeeded":
      return { kind: "connected" };
    case "in_progress":
      return { kind: "verifying" };
    case "failed":
      return {
        kind: "failed",
        message: verification.verificationError?.message ?? null,
      };
    default:
      return { kind: "unverified" };
  }
}

/**
 * The step once a sign-in attempt failed with the API's `code`. A provider
 * that refuses to register AgentArea (`oauth_app_required`) cannot be signed
 * in to from here, so a connection that takes a key asks for it instead.
 */
export function stepAfterSignInError(
  step: ConnectStep,
  code: string | null,
  keyFields: CredentialFieldSpec[]
): ConnectStep {
  if (
    step.kind !== "needs_sign_in" ||
    code !== "oauth_app_required" ||
    keyFields.length === 0
  ) {
    return step;
  }
  return { kind: "needs_key", fields: keyFields, replace: false };
}
