"use client";

import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui/badge";
import { InfoPanelHeader } from "@/components/InfoPanel";
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
    status === "connected"
      ? "teal"
      : status === "running" || status === "healthy"
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
    status === "connected"
      ? tPage("status.connected")
      : status === "running" || status === "healthy"
        ? tPage("status.running")
        : status === "starting"
          ? tPage("status.starting")
          : status === "stopped"
            ? t("status.stopped")
            : status === "error" || status === "unhealthy"
              ? tPage("status.error")
              : status || t("status.unknown");

  return (
    <InfoPanelHeader
      label={t("header.label")}
      title={instance.name || t("header.untitled")}
      right={
        <Badge variant={statusVariant as any} size="sm">
          {statusLabel}
        </Badge>
      }
    />
  );
}
