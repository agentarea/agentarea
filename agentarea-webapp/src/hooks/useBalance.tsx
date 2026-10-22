"use client";

import { createContext, createElement, type ReactNode, useContext } from "react";
import type { BalanceState } from "@/lib/balance";

const BalanceContext = createContext<BalanceState>({ status: "none" });

/** The balance the workspace layout read on the server. */
export function BalanceProvider({
  balance,
  children,
}: {
  balance: BalanceState;
  children: ReactNode;
}) {
  return createElement(BalanceContext.Provider, { value: balance }, children);
}

export function useBalance(): BalanceState {
  return useContext(BalanceContext);
}
