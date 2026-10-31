"use client";

import { useLocale, useTranslations } from "next-intl";
import { CreditCard } from "lucide-react";
import { BoardSectionHeader } from "@/components/board";
import { Button } from "@/components/ui/button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import { useBalance } from "@/hooks/useBalance";
import { formatMoney } from "@/lib/money";
import { useWorkspaceBillingUrl } from "@/lib/use-billing-url";
import { cn } from "@/lib/utils";

const LOW_RUNWAY_DAYS = 3;

/** The payer's balance as its own board section; nothing on a deployment that sells none. */
export function BalanceSection({ className }: { className?: string }) {
  const t = useTranslations("Balance");
  const locale = useLocale();
  const state = useBalance();
  const billingUrl = useWorkspaceBillingUrl();

  if (state.status === "none") return null;

  const balance = state.status === "ready" ? state.balance : null;
  const canTopUp = Boolean(billingUrl && balance?.viewer_is_payer);

  let value: string;
  let hint: string | null = null;
  if (!balance) {
    value = t("unavailable");
  } else if (balance.amount === null) {
    value = balance.exhausted ? t("exhaustedShort") : t("paidByOwner");
  } else {
    value = formatMoney(Number(balance.amount), balance.currency, locale);
    if (balance.exhausted) hint = t("exhaustedHint");
  }

  let runway: { text: string; low: boolean } | null = null;
  if (
    balance?.runway_days != null &&
    balance.spend_per_day != null &&
    !balance.exhausted
  ) {
    const days = Number(balance.runway_days);
    const perDay = formatMoney(
      Number(balance.spend_per_day),
      balance.currency,
      locale
    );
    runway = {
      text:
        days < 1
          ? t("runwayUnderDay", { perDay })
          : t("runway", { days: Math.floor(days), perDay }),
      low: days < LOW_RUNWAY_DAYS,
    };
  }

  return (
    <div
      className={cn(
        "border-b border-dashed border-zinc-300 px-6 pb-4 pt-4 dark:border-zinc-700",
        className
      )}
    >
      <BoardSectionHeader
        icon={<CreditCard />}
        color="hsl(var(--foreground))"
        title={t("label")}
        meta={
          canTopUp && billingUrl ? (
            <Button asChild size="sm">
              <Link href={billingUrl}>{t("topUp")}</Link>
            </Button>
          ) : undefined
        }
      />
      <div className="mt-2.5 flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span
          className={cn(
            "tabular-nums",
            balance?.amount != null
              ? "text-[24px] font-semibold leading-none tracking-[-0.03em]"
              : "text-[14px] text-muted-foreground",
            balance?.exhausted && "text-red-600 dark:text-red-400"
          )}
        >
          {value}
        </span>
        {hint ? (
          <span className="text-[12.5px] text-muted-foreground">{hint}</span>
        ) : null}
      </div>
      {runway ? (
        <div className="mt-1.5 text-[12.5px] tabular-nums text-muted-foreground">
          {runway.low ? (
            <StatusIndicator
              kind="attention"
              size="sm"
              className="text-[12.5px] text-foreground"
            >
              {runway.text}
            </StatusIndicator>
          ) : (
            runway.text
          )}
        </div>
      ) : null}
    </div>
  );
}
