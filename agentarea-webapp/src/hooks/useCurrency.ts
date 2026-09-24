"use client";

import { useEffect, useState } from "react";
import { DEFAULT_CURRENCY } from "@/lib/money";
import { getPricingCurrencyAction } from "@/lib/server-actions";

// Module-level cache shared by every useCurrency() call on the page: the
// workspace's billing currency essentially never changes mid-session, so one
// fetch should serve every component that needs it instead of one request
// each (the long-staleTime behaviour the plan asks for, without pulling in a
// query library this app doesn't otherwise use).
const STALE_TIME_MS = 60 * 60 * 1000;
let cachedCurrency: string | null = null;
let cachedAt = 0;
let inflight: Promise<string> | null = null;

// Bumped by resetCurrencyCache(). A fetch that was already in flight when a
// reset happens carries the OLD generation, so its own resolution (however
// late) must never overwrite a fresher fetch's result — otherwise the
// slower of the two requests wins the race, not the newer one.
let generation = 0;

// Every mounted useCurrency() instance registers its own refetch-and-render
// callback here. `router.refresh()` (App Router) re-fetches Server Component
// data but does NOT unmount already-mounted Client Components, so merely
// clearing the module vars above would leave every live component holding
// the previous workspace's currency for up to an hour after a workspace
// switch — this broadcast is what actually gets them to re-render.
const listeners = new Set<() => void>();

function isFresh(): boolean {
  return cachedCurrency !== null && Date.now() - cachedAt < STALE_TIME_MS;
}

async function fetchCurrency(): Promise<string> {
  try {
    const { data } = await getPricingCurrencyAction();
    return data?.currency || DEFAULT_CURRENCY;
  } catch {
    return DEFAULT_CURRENCY;
  }
}

/**
 * Invalidate the cached currency and force every mounted `useCurrency()`
 * instance to refetch. Call this whenever the active workspace changes
 * (e.g. in TeamSwitcher, before `router.refresh()`) — a workspace switch can
 * change the billing currency (a USD workspace and a RUB workspace read the
 * same numbers ×95 apart), and nothing else notices that switch client-side.
 */
export function resetCurrencyCache(): void {
  generation += 1;
  cachedCurrency = null;
  cachedAt = 0;
  inflight = null;
  listeners.forEach((reload) => reload());
}

/**
 * The workspace's billing currency (C2). Defaults to "USD" while loading and
 * on any error — a failed lookup must not block money from rendering, and
 * must never mislabel a USD amount as another currency.
 */
export function useCurrency(): { currency: string; isLoading: boolean } {
  const [currency, setCurrency] = useState<string>(
    cachedCurrency ?? DEFAULT_CURRENCY
  );
  const [isLoading, setIsLoading] = useState<boolean>(!isFresh());

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      if (isFresh()) {
        setCurrency(cachedCurrency as string);
        setIsLoading(false);
        return;
      }

      const gen = generation;
      setIsLoading(true);
      if (!inflight) {
        inflight = fetchCurrency().finally(() => {
          // Only clear the shared slot if a reset hasn't already replaced it
          // with a newer fetch (or nulled it) — this fetch is stale, and
          // clearing `inflight` here would wipe out that newer one's
          // reference out from under it.
          if (generation === gen) inflight = null;
        });
      }
      inflight.then((value) => {
        if (cancelled) return;
        if (generation !== gen) {
          // A reset happened while this fetch was in flight. A fresher fetch
          // already applied (or is about to apply) its own result — writing
          // this stale one now would overwrite the new workspace's currency
          // with the old one's, however late this one happens to resolve.
          return;
        }
        cachedCurrency = value;
        cachedAt = Date.now();
        setCurrency(value);
        setIsLoading(false);
      });
    };

    load();
    listeners.add(load);
    return () => {
      cancelled = true;
      listeners.delete(load);
    };
  }, []);

  return { currency, isLoading };
}
