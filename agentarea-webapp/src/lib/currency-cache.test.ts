import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  getCurrencyCacheState,
  loadCurrency,
  resetCurrencyCache,
  subscribeToCurrencyCache,
} from "./currency-cache";

describe("currency-cache", () => {
  beforeEach(() => {
    resetCurrencyCache();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("reports 'loading' with no currency before anything has loaded", () => {
    expect(getCurrencyCacheState()).toEqual({
      currency: null,
      status: "loading",
    });
  });

  it("caches a successful fetch as 'ready'", async () => {
    const state = await loadCurrency(async () => "EUR");
    expect(state).toEqual({ currency: "EUR", status: "ready" });
    expect(getCurrencyCacheState()).toEqual({
      currency: "EUR",
      status: "ready",
    });
  });

  it("treats a fetcher returning null as a failed lookup, never as USD", async () => {
    const state = await loadCurrency(async () => null);
    expect(state).toEqual({ currency: null, status: "error" });
    expect(getCurrencyCacheState()).toEqual({
      currency: null,
      status: "error",
    });
  });

  it("treats a rejected fetch as a failed lookup, never as USD", async () => {
    const state = await loadCurrency(() =>
      Promise.reject(new Error("network"))
    );
    expect(state).toEqual({ currency: null, status: "error" });
  });

  it("de-dupes concurrent callers: the fetcher runs once", async () => {
    let resolveFetch: (value: string | null) => void = () => {};
    const fetcher = vi.fn(
      () =>
        new Promise<string | null>((resolve) => {
          resolveFetch = resolve;
        })
    );

    const first = loadCurrency(fetcher);
    const second = loadCurrency(fetcher);
    expect(fetcher).toHaveBeenCalledTimes(1);

    resolveFetch("USD");
    const [firstResult, secondResult] = await Promise.all([first, second]);
    expect(firstResult).toEqual({ currency: "USD", status: "ready" });
    expect(secondResult).toEqual({ currency: "USD", status: "ready" });
  });

  it("expires a cached entry after the stale window elapses", async () => {
    vi.useFakeTimers();
    try {
      await loadCurrency(async () => "USD");
      expect(getCurrencyCacheState().status).toBe("ready");

      vi.advanceTimersByTime(61 * 60 * 1000); // > 60 min stale window
      expect(getCurrencyCacheState()).toEqual({
        currency: null,
        status: "loading",
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("resetCurrencyCache() clears the cache back to 'loading'", async () => {
    await loadCurrency(async () => "USD");
    expect(getCurrencyCacheState().status).toBe("ready");

    resetCurrencyCache();
    expect(getCurrencyCacheState()).toEqual({
      currency: null,
      status: "loading",
    });
  });

  it("resetCurrencyCache() notifies every subscribed listener", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToCurrencyCache(listener);
    try {
      resetCurrencyCache();
      expect(listener).toHaveBeenCalledTimes(1);
    } finally {
      unsubscribe();
    }
  });

  it("an unsubscribed listener stops receiving resets", () => {
    const listener = vi.fn();
    const unsubscribe = subscribeToCurrencyCache(listener);
    unsubscribe();

    resetCurrencyCache();
    expect(listener).not.toHaveBeenCalled();
  });

  it("drops a fetch's result if a reset happens while it is in flight, even if it resolves last", async () => {
    let resolveStale: (value: string | null) => void = () => {};
    const staleFetch = loadCurrency(
      () =>
        new Promise<string | null>((resolve) => {
          resolveStale = resolve;
        })
    );

    // Workspace switch happens before the first (now-stale) fetch resolves.
    resetCurrencyCache();

    // The fresh, post-reset fetch resolves first.
    const freshResult = await loadCurrency(async () => "RUB");
    expect(freshResult).toEqual({ currency: "RUB", status: "ready" });
    expect(getCurrencyCacheState()).toEqual({
      currency: "RUB",
      status: "ready",
    });

    // The stale fetch (from before the reset) resolves last — it must not
    // overwrite the fresh RUB result with its own (older) answer.
    resolveStale("USD");
    await staleFetch;
    expect(getCurrencyCacheState()).toEqual({
      currency: "RUB",
      status: "ready",
    });
  });
});
