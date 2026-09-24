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
    if (isFresh()) {
      setCurrency(cachedCurrency as string);
      setIsLoading(false);
      return;
    }

    let cancelled = false;
    setIsLoading(true);
    if (!inflight) {
      inflight = fetchCurrency().finally(() => {
        inflight = null;
      });
    }
    inflight.then((value) => {
      cachedCurrency = value;
      cachedAt = Date.now();
      if (cancelled) return;
      setCurrency(value);
      setIsLoading(false);
    });

    return () => {
      cancelled = true;
    };
  }, []);

  return { currency, isLoading };
}
