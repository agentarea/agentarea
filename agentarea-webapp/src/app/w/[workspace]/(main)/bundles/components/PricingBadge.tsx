"use client";

import { Coins, KeyRound } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import type {
  CatalogItemPricingResponse,
  CatalogToolPrice,
} from "@/api/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { formatPriceAmount, isPerCall } from "./catalog-pricing";

/** "0,04 ₽/вызов": a tool price per call, or per the unit it is metered in. */
export function usePriceLabel() {
  const t = useTranslations("CatalogPage.pricing");
  const locale = useLocale();
  return (price: CatalogToolPrice) => {
    const amount = formatPriceAmount(price, locale);
    return isPerCall(price)
      ? t("perCall", { price: amount })
      : t("perUnit", { price: amount, unit: price.unit });
  };
}

/**
 * Whether using a catalog connection costs money: paid through AgentArea (from
 * its cheapest call), billed by the vendor on the workspace's own key, or
 * nothing for a free one.
 */
export function PricingBadge({
  pricing,
}: {
  pricing: CatalogItemPricingResponse;
}) {
  const t = useTranslations("CatalogPage.pricing");
  const priceLabel = usePriceLabel();
  if (pricing.kind === "paid") {
    return (
      <Badge variant="amber" size="sm" className="shrink-0 gap-1">
        <Coins className="h-3 w-3" />
        {pricing.price_from
          ? t("paidFrom", { price: priceLabel(pricing.price_from) })
          : t("paid")}
      </Badge>
    );
  }
  if (pricing.kind === "own_key") {
    return (
      <Badge variant="secondary" size="sm" className="shrink-0 gap-1">
        <KeyRound className="h-3 w-3" />
        {t("ownKey")}
      </Badge>
    );
  }
  return null;
}
