"use client";

import { useTranslations } from "next-intl";
import { InfoPanelHeader } from "@/components/InfoPanel";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getMcpVerificationStatusPresentation } from "@/lib/status";
import type { MCPInstance } from "../types";
import { getEffectiveMCPVerificationStatus } from "../utils";

export default function MCPInstanceInfoHeader({
  instance,
}: {
  instance: MCPInstance;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");

  const vStatus = getEffectiveMCPVerificationStatus(instance);
  const statusPresentation = getMcpVerificationStatusPresentation(vStatus);

  return (
    <InfoPanelHeader
      label={t("header.label")}
      title={instance.name || t("header.untitled")}
      right={
        <StatusIndicator
          size="sm"
          tone={statusPresentation.tone}
          pulse={statusPresentation.pulse}
        >
          {statusPresentation.label}
        </StatusIndicator>
      }
    />
  );
}
