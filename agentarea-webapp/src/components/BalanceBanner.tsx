"use client";

import { useTranslations } from "next-intl";
import NoticeBanner from "@/components/NoticeBanner";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { useBalance } from "@/hooks/useBalance";
import { useWorkspaceBillingUrl } from "@/lib/use-billing-url";

/** Across every workspace page while the payer's balance is out: nothing on AgentArea models starts. */
export function BalanceBanner() {
  const t = useTranslations("Balance");
  const state = useBalance();
  const billingUrl = useWorkspaceBillingUrl();

  if (state.status !== "ready" || !state.balance.exhausted) return null;

  const payer = state.balance.viewer_is_payer;
  return (
    <NoticeBanner
      title={t("exhaustedShort")}
      className="shrink-0 rounded-none border-0 border-b"
      action={
        payer && billingUrl ? (
          <Button asChild size="sm">
            <Link href={billingUrl}>{t("topUp")}</Link>
          </Button>
        ) : undefined
      }
    >
      {payer ? t("bannerPayer") : t("bannerMember")}
    </NoticeBanner>
  );
}
