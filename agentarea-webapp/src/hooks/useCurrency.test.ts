// @vitest-environment jsdom

import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { getPricingCurrencyAction } = vi.hoisted(() => ({
  getPricingCurrencyAction: vi.fn(),
}));

vi.mock("@/lib/server-actions", () => ({ getPricingCurrencyAction }));

// Imported after the mock so useCurrency.ts picks up the mocked server action.
const { resetCurrencyCache, useCurrency } = await import("./useCurrency");

describe("useCurrency", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    resetCurrencyCache();
  });

  afterEach(cleanup);

  it("fetches the currency once and reuses it for a second mounted instance (cache hit)", async () => {
    getPricingCurrencyAction.mockResolvedValue({ data: { currency: "EUR" } });

    const first = renderHook(() => useCurrency());
    expect(first.result.current.isLoading).toBe(true);
    await waitFor(() => expect(first.result.current.currency).toBe("EUR"));
    expect(first.result.current.isLoading).toBe(false);

    const second = renderHook(() => useCurrency());
    // Cached already — no loading flash, no extra fetch.
    expect(second.result.current).toEqual({
      currency: "EUR",
      isLoading: false,
    });
    expect(getPricingCurrencyAction).toHaveBeenCalledTimes(1);
  });

  it("de-dupes concurrent fetches from instances mounted before the first resolves", async () => {
    let resolveFetch: (value: { data: { currency: string } }) => void;
    getPricingCurrencyAction.mockReturnValue(
      new Promise((resolve) => {
        resolveFetch = resolve;
      })
    );

    const a = renderHook(() => useCurrency());
    const b = renderHook(() => useCurrency());
    expect(a.result.current.isLoading).toBe(true);
    expect(b.result.current.isLoading).toBe(true);

    await act(async () => {
      resolveFetch({ data: { currency: "RUB" } });
      await Promise.resolve();
    });

    await waitFor(() => expect(a.result.current.currency).toBe("RUB"));
    await waitFor(() => expect(b.result.current.currency).toBe("RUB"));
    // Two instances mounted while the fetch was in flight share the one call.
    expect(getPricingCurrencyAction).toHaveBeenCalledTimes(1);
  });

  it("falls back to USD when the fetch rejects", async () => {
    getPricingCurrencyAction.mockRejectedValue(new Error("network error"));

    const { result } = renderHook(() => useCurrency());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.currency).toBe("USD");
  });

  it("falls back to USD when the action resolves without a currency", async () => {
    getPricingCurrencyAction.mockResolvedValue({ data: null });

    const { result } = renderHook(() => useCurrency());
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.currency).toBe("USD");
  });

  it("resetCurrencyCache() forces every mounted instance to refetch and update (workspace switch)", async () => {
    getPricingCurrencyAction.mockResolvedValue({ data: { currency: "USD" } });
    const { result } = renderHook(() => useCurrency());
    await waitFor(() => expect(result.current.currency).toBe("USD"));

    // Switching workspace: the new workspace bills in RUB.
    getPricingCurrencyAction.mockResolvedValue({ data: { currency: "RUB" } });
    act(() => {
      resetCurrencyCache();
    });

    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.currency).toBe("RUB"));
    expect(result.current.isLoading).toBe(false);
    expect(getPricingCurrencyAction).toHaveBeenCalledTimes(2);
  });
});
