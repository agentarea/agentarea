import type { BalanceResponse } from "@/api/client";

/**
 * The payer's balance as the UI knows it. `none`: this deployment sells nothing
 * (the open build), so there is no balance to show anywhere.
 */
export type BalanceState =
  | { status: "none" }
  | { status: "error" }
  | { status: "ready"; balance: BalanceResponse };
