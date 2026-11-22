import type { SessionIdentity } from "@/lib/auth-session";

/**
 * The OIDC standard claims a client gets in its ID token and from userinfo,
 * gated by the scopes it was granted: `email` → email and email_verified,
 * `profile` → name, given_name, family_name, preferred_username, picture.
 * Empty traits are left out rather than sent as "".
 */
export function identityClaims(
  grantedScope: string[],
  identity: SessionIdentity
): Record<string, string | boolean> {
  const claims: Record<string, string | boolean> = {};
  const traits = identity.traits;
  const text = (v: unknown) => (typeof v === "string" && v.trim() ? v.trim() : undefined);

  if (grantedScope.includes("email")) {
    const email = text(traits.email);
    if (email) {
      claims.email = email;
      claims.email_verified = identity.verifiedEmails.includes(email.toLowerCase());
    }
  }

  if (grantedScope.includes("profile")) {
    const name = (traits.name ?? {}) as Record<string, unknown>;
    const given = text(name.first);
    const family = text(name.last);
    const full = [given, family].filter(Boolean).join(" ");
    if (full) claims.name = full;
    if (given) claims.given_name = given;
    if (family) claims.family_name = family;
    const username = text(traits.username);
    if (username) claims.preferred_username = username;
    const picture = text(traits.picture);
    if (picture) claims.picture = picture;
  }

  return claims;
}
