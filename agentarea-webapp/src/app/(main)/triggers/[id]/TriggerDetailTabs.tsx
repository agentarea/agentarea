"use client";

import { useTranslations } from "next-intl";
import { LayoutDashboard, List, BarChart3 } from "lucide-react";
import { ActiveLink } from "@/components/ui/active-link";

export default function TriggerDetailTabs({
  triggerId,
}: {
  triggerId: string;
}) {
  const t = useTranslations("TriggersPage.detail");

  return (
    <div className="inline-flex items-center gap-3 py-2">
      <ActiveLink href={`/triggers/${triggerId}`}>
        <LayoutDashboard className="h-4 w-4" />
        {t("overview")}
      </ActiveLink>
      <ActiveLink href={`/triggers/${triggerId}/executions`}>
        <List className="h-4 w-4" />
        {t("executions")}
      </ActiveLink>
      <ActiveLink href={`/triggers/${triggerId}/metrics`}>
        <BarChart3 className="h-4 w-4" />
        {t("metrics")}
      </ActiveLink>
    </div>
  );
}
