"use client";

import { useTranslations } from "next-intl";
import { BadgeCheck, Lock, ShieldCheck, Users } from "lucide-react";
import type { RegistryResponse } from "@/api/client/types.gen";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

export type RegistryTrust = RegistryResponse["trust"];

const TRUST_ICON = {
  official: BadgeCheck,
  verified: ShieldCheck,
  community: Users,
  private: Lock,
} satisfies Record<RegistryTrust, unknown>;

const TRUST_VARIANT = {
  official: "blue",
  verified: "sky",
  community: "secondary",
  private: "zinc",
} as const satisfies Record<RegistryTrust, string>;

/** How far a registry is trusted, as the label the rest of the UI uses. */
export function useRegistryTrustLabel() {
  const t = useTranslations("Registries.trust");
  return (trust: RegistryTrust) => t(trust);
}

/**
 * Where a catalog entry comes from: its registry's name and trust level. Every
 * catalog card carries one, so an unvetted source never reads like ours.
 */
export function RegistryBadge({
  name,
  trust,
  className,
}: {
  name?: string | null;
  trust: RegistryTrust;
  className?: string;
}) {
  const trustLabel = useRegistryTrustLabel()(trust);
  const Icon = TRUST_ICON[trust];
  const label = name ? `${name} · ${trustLabel}` : trustLabel;

  return (
    <Badge
      variant={TRUST_VARIANT[trust]}
      size="sm"
      title={label}
      className={cn("max-w-full gap-1 font-normal", className)}
    >
      <Icon aria-hidden className="h-3 w-3 shrink-0" />
      <span className="truncate">{label}</span>
    </Badge>
  );
}
