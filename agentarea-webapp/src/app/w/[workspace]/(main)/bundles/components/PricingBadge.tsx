"use client";

import {
  Banknote,
  Cpu,
  DollarSign,
  KeyRound,
  RussianRuble,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type {
  CatalogComputeEstimate,
  CatalogItemPricingResponse,
  CatalogToolPrice,
} from "@/api/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import {
  formatMoney,
  formatPriceNumber,
  isPerCall,
} from "./catalog-pricing";

/**
 * A tool price per call, or per the unit it is metered in: "0,04 / вызов" for
 * a chip whose icon names the currency, "0,04 ₽ / вызов" read out in full.
 */
export function usePriceLabel() {
  const t = useTranslations("CatalogPage.pricing");
  const locale = useLocale();
  return (price: CatalogToolPrice, { full = false } = {}) => {
    const amount = full
      ? formatMoney(price.amount, price.currency, locale)
      : formatPriceNumber(price.amount, locale);
    return isPerCall(price)
      ? t("perCall", { price: amount })
      : t("perUnit", { price: amount, unit: price.unit });
  };
}

function CurrencyIcon({ currency }: { currency?: string }) {
  const Icon =
    currency === "RUB"
      ? RussianRuble
      : currency === "USD"
        ? DollarSign
        : Banknote;
  return (
    <Icon
      aria-hidden="true"
      className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-300"
    />
  );
}

/**
 * A green chip that leads with what a call costs. The icon names the currency,
 * so the text carries the amount alone; `label` is the full price, with its
 * currency, for the tooltip and screen readers.
 */
export function PriceChip({
  currency,
  label,
  children,
  className,
}: {
  currency?: string;
  label: string;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <Badge
      variant="emerald"
      title={label}
      className={cn("shrink-0 font-medium tabular-nums", className)}
    >
      <CurrencyIcon currency={currency} />
      <span aria-hidden="true">{children}</span>
      <span className="sr-only">{label}</span>
    </Badge>
  );
}

/** "≈ 0,12 ₽/ч": what an hour of a hosted server's reserved compute costs. */
export function ComputeChip({
  compute,
}: {
  compute: CatalogComputeEstimate;
}) {
  const t = useTranslations("CatalogPage.pricing");
  const locale = useLocale();
  if (compute.hourly == null || !compute.currency) return null;
  const hourly = formatMoney(compute.hourly, compute.currency, locale);
  return (
    <Badge
      variant="sky"
      title={t("computeChipTitle", { hourly })}
      className="shrink-0 font-normal tabular-nums"
    >
      <Cpu aria-hidden="true" className="h-3.5 w-3.5 shrink-0" />
      <span aria-hidden="true">{t("computeHourly", { price: hourly })}</span>
      <span className="sr-only">{t("computeChipTitle", { hourly })}</span>
    </Badge>
  );
}

/**
 * Whether using a catalog connection costs money: paid through AgentArea (from
 * its cheapest call), billed by the vendor on the workspace's own key, or
 * nothing for a free one. A server AgentArea runs adds what an hour of its
 * reserved compute costs, beside and apart from the per-call price.
 */
export function PricingBadge({
  pricing,
}: {
  pricing: CatalogItemPricingResponse;
}) {
  const t = useTranslations("CatalogPage.pricing");
  const priceLabel = usePriceLabel();
  const compute = pricing.compute && <ComputeChip compute={pricing.compute} />;
  if (pricing.kind === "paid") {
    const from = pricing.price_from;
    return (
      <>
        <PriceChip
          currency={from?.currency}
          label={
            from
              ? t("from", { price: priceLabel(from, { full: true }) })
              : t("paid")
          }
        >
          {from ? t("from", { price: priceLabel(from) }) : t("paid")}
        </PriceChip>
        {compute}
      </>
    );
  }
  if (pricing.kind === "own_key") {
    return (
      <>
        <Badge variant="secondary" size="sm" className="shrink-0 font-normal">
          <KeyRound aria-hidden="true" className="h-3 w-3 shrink-0" />
          {t("ownKey")}
        </Badge>
        {compute}
      </>
    );
  }
  return compute || null;
}
