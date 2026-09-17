import "server-only";
import { env } from "@/env";
import { KRATOS_WHOAMI_TIMEOUT_MS } from "@/lib/server-timeouts";

/** Profile details the identity provider knows about a user. */
export interface IdentityProfile {
  email: string | null;
  name: string | null;
  username: string | null;
}

type KratosIdentity = {
  id?: string;
  traits?: {
    email?: unknown;
    username?: unknown;
    name?: unknown;
  };
};

function stringOrNull(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Kratos stores the name as `{ first, last }`; older schemas used a string. */
function nameOrNull(value: unknown): string | null {
  if (typeof value === "string") return stringOrNull(value);
  if (!value || typeof value !== "object") return null;
  const name = value as { first?: unknown; last?: unknown };
  const parts = [name.first, name.last].filter(
    (part): part is string => typeof part === "string" && part.length > 0
  );
  return parts.length > 0 ? parts.join(" ") : null;
}

export function identityToProfile(identity: KratosIdentity): IdentityProfile {
  return {
    email: stringOrNull(identity.traits?.email),
    name: nameOrNull(identity.traits?.name),
    username: stringOrNull(identity.traits?.username),
  };
}

async function fetchIdentity(
  id: string,
  fetchImpl: typeof fetch
): Promise<IdentityProfile | null> {
  const response = await fetchImpl(
    `${env.ORY_ADMIN_URL}/admin/identities/${encodeURIComponent(id)}`,
    {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(KRATOS_WHOAMI_TIMEOUT_MS),
      cache: "no-store",
    }
  );
  if (!response.ok) return null;
  return identityToProfile((await response.json()) as KratosIdentity);
}

/**
 * Resolve user ids to the profiles the identity provider holds for them.
 *
 * The backend only returns profile details for the caller — other members
 * come back as bare user ids — so the members page asks Kratos' admin API
 * directly. Server-only: the admin API must never be reachable from the
 * browser. Fail-soft: an unreachable admin API (or an unknown id) simply
 * leaves that user unresolved, and the page falls back to the id.
 */
export async function resolveIdentityProfiles(
  ids: string[],
  fetchImpl: typeof fetch = fetch
): Promise<Map<string, IdentityProfile>> {
  const profiles = new Map<string, IdentityProfile>();
  // Deployments without an admin URL (or a deliberately unset one) just show
  // members by id; that's a configuration choice, not an error to log.
  if (!env.ORY_ADMIN_URL) return profiles;
  const unique = Array.from(new Set(ids.filter(Boolean)));
  if (unique.length === 0) return profiles;

  const results = await Promise.allSettled(
    unique.map(async (id) => [id, await fetchIdentity(id, fetchImpl)] as const)
  );
  for (const result of results) {
    if (result.status !== "fulfilled") {
      console.error("[identities] failed to resolve identity:", result.reason);
      continue;
    }
    const [id, profile] = result.value;
    if (profile) profiles.set(id, profile);
  }
  return profiles;
}
