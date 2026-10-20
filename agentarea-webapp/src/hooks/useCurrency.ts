"use client";

import {
  createContext,
  createElement,
  type ReactNode,
  useContext,
  useEffect,
  useState,
} from "react";
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

const ServerCurrencyContext = createContext<string | null>(null);

/**
 * The billing currency the workspace layout resolved on the server, so money
 * renders in it from the first paint instead of after a client lookup.
 */
export function CurrencyProvider({
  currency,
  children,
}: {
  currency: string | null;
  children: ReactNode;
}) {
  return createElement(
    ServerCurrencyContext.Provider,
    { value: currency },
    children
  );
}

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
  const serverCurrency = useContext(ServerCurrencyContext);
  const [state, setState] = useState<CurrencyState>(() =>
    getCurrencyCacheState()
  );

  useEffect(() => {
    if (serverCurrency) return;
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
  }, [serverCurrency]);

  return serverCurrency
    ? { currency: serverCurrency, status: "ready" }
    : state;
}
