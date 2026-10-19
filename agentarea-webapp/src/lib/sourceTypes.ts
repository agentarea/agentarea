import type { SourceTypeResponse } from "@/api/client/types.gen";

/**
 * One catalog entry (ADR-0040 §2): how a provider's events arrive, its name and
 * artwork. Which providers exist is the catalog's business, so nothing in the
 * webapp names one; every label and icon comes from an entry.
 */
export type SourceType = SourceTypeResponse;

/** The `generic_webhook` entry's slug: a provider the catalog has no entry for. */
export const GENERIC_WEBHOOK = "generic_webhook";

/** How long a session's task waits for its next event, as the API spells it. */
export const SESSION_IDLE_TIMEOUTS = ["5m", "15m", "30m", "1h", "4h", "24h"];
export const DEFAULT_SESSION_IDLE_TIMEOUT = "30m";

export function sourceTypeBySlug(
  types: readonly SourceType[],
  slug: string | null | undefined
): SourceType | undefined {
  return slug ? types.find((type) => type.slug === slug) : undefined;
}

/**
 * The `session.continue` default for a trigger on a stream fed by sources of
 * `slugs`: on when any of them names the session an event belongs to.
 */
export function streamContinuesSessions(
  types: readonly SourceType[],
  slugs: readonly (string | null | undefined)[]
): boolean {
  return slugs.some((slug) => {
    const type = sourceTypeBySlug(types, slug);
    return type?.continues_sessions ?? false;
  });
}

export interface ResolvedSession {
  continue: boolean;
  idle_timeout: string;
}

/** A trigger's session setting before anyone changes it. */
export function defaultSession(continues: boolean): ResolvedSession {
  return { continue: continues, idle_timeout: DEFAULT_SESSION_IDLE_TIMEOUT };
}

/** A stored session setting with each null filled by the stream's default. */
export function resolveSession(
  session:
    | { continue?: boolean | null; idle_timeout?: string | null }
    | null
    | undefined,
  continues: boolean
): ResolvedSession {
  return {
    continue: session?.continue ?? continues,
    idle_timeout: session?.idle_timeout ?? DEFAULT_SESSION_IDLE_TIMEOUT,
  };
}
