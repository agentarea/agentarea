/**
 * True only when the authenticated session's identity is the subject Hydra's
 * consent request was issued for.
 *
 * A live session alone is not enough: without this check, any logged-in
 * user could accept or view a consent challenge that belongs to a different
 * user's login (the subject Hydra recorded when that user's login challenge
 * was accepted).
 */
export function sessionMatchesConsentSubject(
  sessionIdentityId: string | null,
  consentSubject: string | undefined
): boolean {
  return Boolean(sessionIdentityId) && sessionIdentityId === consentSubject;
}
