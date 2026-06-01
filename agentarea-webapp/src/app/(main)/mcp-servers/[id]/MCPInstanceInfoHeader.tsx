"use client";

import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { Badge } from "@/components/ui/badge";
import type { MCPInstance } from "../types";
import { getEffectiveMCPVerificationStatus } from "../utils";

export default function MCPInstanceInfoHeader({
  instance,
}: {
  instance: MCPInstance;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");

  const vStatus = getEffectiveMCPVerificationStatus(instance);

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
