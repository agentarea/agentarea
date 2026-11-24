"use client";

import { useLocale, useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
} from "@/components/ui/sidebar";
import Link from "@/components/WorkspaceLink";
import { useBalance } from "@/hooks/useBalance";
import { formatMoney } from "@/lib/money";
import { useWorkspaceBillingUrl } from "@/lib/use-billing-url";
import { cn } from "@/lib/utils";
import { navItemClassName } from "./NavMain";

const LOW_RUNWAY_DAYS = 3;

/**
 * The balance as a sidebar row above Help: the amount, and a dot on the icon
 * when it runs low (amber) or is out (red). While it needs money the row leads
 * to top-up, otherwise to Budgets. A member who does not pay sees the row only
 * once the balance is out. Nothing on a deployment that sells none.
 */
export function SidebarBalance() {
  const t = useTranslations("Balance");
  const locale = useLocale();
  const state = useBalance();
  const billingUrl = useWorkspaceBillingUrl();

  if (state.status !== "ready") return null;
  const balance = state.balance;
  const payer = balance.viewer_is_payer;
  if (!payer && !balance.exhausted) return null;

  const days = balance.runway_days != null ? Number(balance.runway_days) : null;
  const low = !balance.exhausted && days != null && days < LOW_RUNWAY_DAYS;
  const alert = balance.exhausted || low;
  const href = alert && payer && billingUrl ? billingUrl : "/budgets";

  const amount =
    payer && balance.amount !== null
      ? formatMoney(
          Math.floor(Number(balance.amount)),
          balance.currency,
          locale,
          { compact: true }
        )
      : null;

  return (
    <SidebarMenu>
      <SidebarMenuItem>
        <SidebarMenuButton
          asChild
          tooltip={[t("label"), amount].filter(Boolean).join(" ")}
          className={navItemClassName}
        >
          <Link href={href}>
            <span className="relative flex shrink-0">
              <Wallet
                className="size-4 text-zinc-500 dark:text-zinc-400"
                strokeWidth={1.75}
              />
              {alert && (
                <span
                  aria-hidden
                  className={cn(
                    "absolute -right-0.5 -top-0.5 size-1.5 rounded-full ring-2 ring-sidebar",
                    balance.exhausted ? "bg-red-600" : "bg-amber-500"
                  )}
                />
              )}
            </span>
            <span>{t("label")}</span>
            {amount && (
              <span
                className={cn(
                  "ml-auto tabular-nums",
                  balance.exhausted
                    ? "font-medium text-red-600 dark:text-red-400"
                    : "text-zinc-500 dark:text-zinc-400"
                )}
              >
                {amount}
              </span>
            )}
          </Link>
        </SidebarMenuButton>
      </SidebarMenuItem>
    </SidebarMenu>
  );
}
