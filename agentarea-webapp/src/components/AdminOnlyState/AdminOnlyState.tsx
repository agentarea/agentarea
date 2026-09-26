"use client";

import { Lock, ShieldCheck, Users } from "lucide-react";
import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";

export type AdminOnlyArea =
  | "policies"
  | "accessControl"
  | "policyEditor"
  | "auditLog"
  | "networkPeopleAccess"
  | "providerConfigs"
  | "wallet";

/** Replaces a page or section the viewer may not open without a workspace admin. */
export default function AdminOnlyState({ what }: { what: AdminOnlyArea }) {
  const t = useTranslations("AdminOnly");

  return (
    <EmptyState
      title={t(`areas.${what}.title`)}
      description={t(`areas.${what}.description`)}
      icons={[Users, Lock, ShieldCheck]}
      hints={[{ text: t("membersLink"), href: "/members" }]}
    />
  );
}
