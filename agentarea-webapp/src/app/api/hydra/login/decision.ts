export interface LoginRequest {
  skip?: boolean;
  subject?: string;
}

export type LoginDecision =
  | { action: "accept"; body: { subject: string } }
  | {
      action: "reject";
      body: { error: string; error_description: string };
    };

/**
 * What is sent to Hydra for a login request, given the live Kratos session.
 *
 * Nothing is remembered, so Hydra asks again on every login and the live
 * session decides. A login Hydra still skips for an earlier user cannot be
 * accepted as a different one: Hydra requires the remembered subject.
 */
export function loginDecision(
  loginRequest: LoginRequest,
  sessionIdentityId: string
): LoginDecision {
  if (loginRequest.skip && loginRequest.subject !== sessionIdentityId) {
    return {
      action: "reject",
      body: {
        error: "login_required",
        error_description:
          "The browser is signed in as a different user than the one this authorization server remembers; sign in again",
      },
    };
  }
  return { action: "accept", body: { subject: sessionIdentityId } };
}
