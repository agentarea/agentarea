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

  const verification = (instance as any).verification as {
    status: string;
  } | null | undefined;

  const vStatus = verification?.status ?? "never_attempted";

  const statusVariant =
    vStatus === "succeeded"
      ? "success"
      : vStatus === "in_progress"
        ? "yellow"
        : vStatus === "failed"
          ? "destructive"
          : "zinc";

  const statusLabel =
    vStatus === "succeeded"
      ? "Verified"
      : vStatus === "in_progress"
        ? "Verifying"
        : vStatus === "failed"
          ? "Failed"
          : "Not verified";

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
