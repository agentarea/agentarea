import { grantedAccessTokenAudience } from "@/app/auth/consent/oauth-audience";

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
  consentRequest: ConsentRequest
) {
  if (action === "reject") {
    return {
      error: "access_denied",
      error_description: "The user denied the request",
    };
  }
  return {
    grant_scope: consentRequest.requested_scope ?? [],
    grant_access_token_audience: grantedAccessTokenAudience(
      consentRequest.requested_access_token_audience,
      consentRequest.client?.audience
    ),
  };
}
