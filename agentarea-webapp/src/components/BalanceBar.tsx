"use client";

import { useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { useBalance } from "@/hooks/useBalance";
import { useWorkspaceBillingUrl } from "@/lib/use-billing-url";

/** Height the app shell gives up to the bar while it shows. */
export const BALANCE_BAR_HEIGHT = "36px";

/** Whether the payer's balance is out, so the shell makes room for the bar. */
export function useBalanceExhausted(): boolean {
  const state = useBalance();
  return state.status === "ready" && state.balance.exhausted;
}

/**
 * Across the top of the whole app while the payer's balance is out: nothing on
 * AgentArea models starts. It sits above the sidebar and the page, so the two
 * move down together instead of the page header alone; it has no close button
 * because the state it reports does not go away until someone acts.
 */
export function BalanceBar() {
  const t = useTranslations("Balance");
  const state = useBalance();
  const billingUrl = useWorkspaceBillingUrl();

  if (state.status !== "ready" || !state.balance.exhausted) return null;

  const payer = state.balance.viewer_is_payer;
  const topUp = payer && billingUrl ? billingUrl : null;

  return (
    <div
      role="status"
      style={{ height: BALANCE_BAR_HEIGHT }}
      className="flex shrink-0 items-center justify-center gap-3 border-b border-red-200 bg-red-50 px-4 text-[13px] text-foreground dark:border-red-900/60 dark:bg-red-950/40"
    >
      <Wallet
        aria-hidden
        className="size-4 shrink-0 text-red-600 dark:text-red-400"
        strokeWidth={1.8}
      />
      <span className="min-w-0 truncate">
        <span className="font-medium">{t("exhaustedShort")}</span>
        <span className="text-muted-foreground">
          {" — "}
          {payer ? t("exhaustedHint") : t("bannerMember")}
        </span>
      </span>
      {topUp && (
        <Button
          asChild
          size="sm"
          className="h-6 shrink-0 bg-foreground px-2.5 text-xs text-background hover:bg-foreground/85"
        >
          <Link href={topUp}>{t("topUp")}</Link>
        </Button>
      )}
      <Link
        href="/models"
        className="shrink-0 text-xs font-medium text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
      >
        {t("ownKey")}
      </Link>
    </div>
  );
}
