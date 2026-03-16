"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import type { MCPInstance } from "../types";

export default function MCPInstanceInfoHeader({
  instance,
}: {
  instance: MCPInstance;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");
  const tPage = useTranslations("MCPServersPage");

  const status = instance.status;
  const statusVariant =
    status === "running" || status === "healthy"
      ? "success"
      : status === "starting" ||
          status === "pending" ||
          status === "validating" ||
          status === "stopping"
        ? "yellow"
        : status === "stopped"
          ? "secondary"
          : status === "error" || status === "unhealthy"
            ? "destructive"
            : "zinc";

  const statusLabel =
    status === "running" || status === "healthy"
      ? tPage("status.running")
      : status === "starting"
        ? tPage("status.starting")
        : status === "stopped"
          ? t("status.stopped")
          : status === "error" || status === "unhealthy"
            ? tPage("status.error")
            : status || t("status.unknown");

  return (
    <div className="flex items-start justify-between gap-3 px-3 pb-3 pt-3">
      <div className="space-y-1">
        <div className="text-xs font-normal uppercase tracking-wide text-muted-foreground">
          {t("header.label")}
        </div>
        <h3 className="line-clamp-2 text-sm font-semibold text-foreground">
          {instance.name || t("header.untitled")}
        </h3>
      </div>
      <Badge variant={statusVariant as any} size="sm">
        {statusLabel}
      </Badge>
    </div>
  );
}
