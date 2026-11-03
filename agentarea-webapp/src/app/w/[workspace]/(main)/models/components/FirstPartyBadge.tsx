"use client";

import { useTranslations } from "next-intl";
import { BadgeCheck } from "lucide-react";
import { Badge } from "@/components/ui/badge";

/**
 * Marks the provider the platform itself hosts, as the catalog flags it
 * (`is_first_party`); drawn like RegistryBadge's "Official".
 */
export function FirstPartyBadge() {
  const label = useTranslations("Models")("firstPartyBadge");

  return (
    <Badge
      variant="blue"
      size="sm"
      title={label}
      className="shrink-0 gap-1 font-normal"
    >
      <BadgeCheck aria-hidden className="h-3 w-3 shrink-0" />
      <span className="truncate">{label}</span>
    </Badge>
  );
}
