"use client";

import {
  LayoutDashboard,
  Activity,
  Package,
  Brain,
  BarChart3,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { ActiveLink } from "@/components/ui/active-link";

export default function TaskSubheader({ taskId }: { taskId: string }) {
  const t = useTranslations("TasksPage.tabs");

  return (
    <div className="inline-flex items-center gap-3 py-2">
      <ActiveLink href={`/tasks/${taskId}`}>
        <LayoutDashboard className="h-4 w-4" />
        {t("overview")}
      </ActiveLink>
      <ActiveLink href={`/tasks/${taskId}/events`}>
        <Activity className="h-4 w-4" />
        {t("events")}
      </ActiveLink>
      <ActiveLink href={`/tasks/${taskId}/artifacts`}>
        <Package className="h-4 w-4" />
        {t("artifacts")}
      </ActiveLink>
      <ActiveLink href={`/tasks/${taskId}/memory`}>
        <Brain className="h-4 w-4" />
        {t("memory")}
      </ActiveLink>
      <ActiveLink href={`/tasks/${taskId}/metrics`}>
        <BarChart3 className="h-4 w-4" />
        {t("metrics")}
      </ActiveLink>
    </div>
  );
}
