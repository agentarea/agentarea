import { grantedAccessTokenAudience } from "@/app/auth/consent/oauth-audience";
import type { SessionIdentity } from "@/lib/auth-session";
import { identityClaims } from "./identity-claims";

export interface ConsentRequest {
  subject?: string;
  requested_scope?: string[];
  requested_access_token_audience?: string[];
  client?: { audience?: string[] };
}

/**
 * What is sent to Hydra when the user accepts or rejects.
 *
 * Built from the consent request Hydra holds, never from the browser: the
 * browser could otherwise grant itself any scope or audience and put any
 * claim into the tokens.
 */
export function consentDecisionBody(
  action: "accept" | "reject",
  consentRequest: ConsentRequest,
  identity?: SessionIdentity
) {
  if (action === "reject") {
    return {
      error: "access_denied",
      error_description: "The user denied the request",
    };
  }
  const grantScope = consentRequest.requested_scope ?? [];
  const claims = identity ? identityClaims(grantScope, identity) : {};
  return {
    grant_scope: grantScope,
    grant_access_token_audience: grantedAccessTokenAudience(
      consentRequest.requested_access_token_audience,
      consentRequest.client?.audience
    ),
    ...(Object.keys(claims).length > 0 ? { session: { id_token: claims } } : {}),
  };
}
