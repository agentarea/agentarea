"use client";

import { useEffect, useState } from "react";
import {
  getCurrencyCacheState,
  loadCurrency,
  resetCurrencyCache,
  subscribeToCurrencyCache,
  type CurrencyState,
} from "@/lib/currency-cache";
import { getPricingCurrencyAction } from "@/lib/server-actions";

export { resetCurrencyCache };
export type { CurrencyState };

async function fetchCurrency(): Promise<string | null> {
  const { data } = await getPricingCurrencyAction();
  return data?.currency ?? null;
}

/**
 * The workspace's billing currency (C2). Never guesses: `currency` is `null`
 * while `status` is `"loading"` or `"error"` — a failed or not-yet-resolved
 * lookup must never render as USD or any other assumed currency. Render
 * money via `formatMoney(amount, currency, locale)` from `@/lib/money`,
 * which handles a null currency by omitting the currency symbol rather than
 * guessing one.
 *
 * All the caching/de-dupe/staleness/workspace-reset logic lives in the pure
 * `@/lib/currency-cache` module (tested there, without React); this hook
 * just subscribes a component to it.
 */
export function useCurrency(): CurrencyState {
  const [state, setState] = useState<CurrencyState>(() =>
    getCurrencyCacheState()
  );

  useEffect(() => {
    let cancelled = false;

    const load = () => {
      const cached = getCurrencyCacheState();
      setState(cached);
      if (cached.status !== "loading") return;

      loadCurrency(fetchCurrency).then((result) => {
        if (cancelled) return;
        setState(result);
      });
    };

    load();
    const unsubscribe = subscribeToCurrencyCache(load);
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, []);

  return state;
}
