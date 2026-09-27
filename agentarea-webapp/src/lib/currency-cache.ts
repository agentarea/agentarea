/**
 * Pure (no React) cache for the workspace's billing currency: staleness,
 * concurrent-fetch de-duplication, and generation-based invalidation on
 * workspace switch. Wrapped by `useCurrency()` in `@/hooks/useCurrency`,
 * which owns the actual fetch (a server action) and just calls in here for
 * caching/broadcast — this module has no knowledge of the network.
 *
 * Never guesses: a failed or not-yet-resolved lookup is `status: "error"` or
 * `"loading"` with `currency: null`. Nothing in this module invents a
 * currency (e.g. "USD") to paper over an unknown one — see formatMoney in
 * @/lib/money for how a null currency renders.
 */

export type CurrencyStatus = "loading" | "ready" | "error";

export interface CurrencyState {
  currency: string | null;
  status: CurrencyStatus;
}

const STALE_TIME_MS = 60 * 60 * 1000;

interface CacheEntry {
  currency: string | null;
  status: "ready" | "error";
  at: number;
}

let cache: CacheEntry | null = null;
let inflight: Promise<CacheEntry> | null = null;

// Bumped by resetCurrencyCache(). A fetch already in flight when a reset
// happens carries the OLD generation, so its own resolution (however late)
// must never overwrite a fresher fetch's result — otherwise the slower of
// the two requests wins the race, not the newer one.
let generation = 0;

// Every mounted useCurrency() instance registers its own reload callback
// here. router.refresh() (App Router) re-fetches Server Component data but
// does NOT unmount already-mounted Client Components, and this cache is a
// module-level singleton that outlives any one component anyway — this
// broadcast is what actually gets live components to re-render on a reset.
const listeners = new Set<() => void>();

function isFresh(entry: CacheEntry | null): entry is CacheEntry {
  return entry !== null && Date.now() - entry.at < STALE_TIME_MS;
}

/** The cached state right now, without starting a fetch. */
export function getCurrencyCacheState(): CurrencyState {
  if (isFresh(cache)) {
    return { currency: cache.currency, status: cache.status };
  }
  return { currency: null, status: "loading" };
}

/**
 * Invalidate the cache and force every subscriber to reload. Call this
 * whenever the active workspace changes (e.g. in TeamSwitcher, before
 * navigating) — a workspace switch can change the billing currency, and
 * nothing else notices that switch client-side.
 */
export function resetCurrencyCache(): void {
  generation += 1;
  cache = null;
  inflight = null;
  listeners.forEach((listener) => listener());
}

/** Register a callback fired by resetCurrencyCache(); returns an unsubscribe. */
export function subscribeToCurrencyCache(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * Fetch the currency via `fetcher`, de-duped across concurrent callers (a
 * second caller while one fetch is in flight shares the same promise rather
 * than firing a second request). `fetcher` returning `null` — including via
 * rejection — is treated as a failed lookup (`status: "error"`), never as
 * "assume USD".
 *
 * A fetch superseded by resetCurrencyCache() while in flight is dropped: its
 * result (however late it resolves) is neither written to the cache nor
 * returned to the caller that kicked it off — a fresher fetch already has,
 * or is about to have, the real answer.
 */
export async function loadCurrency(
  fetcher: () => Promise<string | null>
): Promise<CurrencyState> {
  const gen = generation;
  if (!inflight) {
    inflight = fetcher()
      .then(
        (currency): CacheEntry => ({
          currency,
          status: currency ? "ready" : "error",
          at: Date.now(),
        })
      )
      .catch(
        (): CacheEntry => ({ currency: null, status: "error", at: Date.now() })
      )
      .finally(() => {
        if (generation === gen) inflight = null;
      });
  }

  const result = await inflight;
  if (generation !== gen) {
    // Superseded — report whatever the (possibly still-loading) current
    // state is rather than this stale fetch's answer.
    return getCurrencyCacheState();
  }
  cache = result;
  return { currency: result.currency, status: result.status };
}
