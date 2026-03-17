"use client";

import { useTranslations } from "next-intl";
import { Clock, Hash } from "lucide-react";
import {
  InfoPanelBody,
  InfoPanelExpandableText,
  InfoPanelField,
  InfoPanelSection,
  InfoPanelShell,
  InfoPanelValueBox,
} from "@/components/InfoPanel";
import type { MCPInstance, MCPServer } from "../types";
import MCPInstanceInfoHeader from "./MCPInstanceInfoHeader";

export default function MCPInstancePanel({
  instance,
  serverSpec,
}: {
  instance: MCPInstance;
  serverSpec: MCPServer | null;
}) {
  const t = useTranslations("MCPServersPage.instanceDetail");

  return (
    <InfoPanelShell>
      <MCPInstanceInfoHeader instance={instance} />

      <InfoPanelBody>
        <InfoPanelSection
          title={t("details.title")}
          contentClassName="space-y-3 text-xs"
        >
            <div className="space-y-1">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("fields.name")}
              </div>
              <div className="text-sm font-semibold text-foreground">
                {instance.name || "-"}
              </div>
            </div>

            <div className="space-y-1">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("fields.description")}
              </div>
              {instance.description ? (
                <InfoPanelExpandableText
                  content={instance.description}
                  maxLines={3}
                  textClassName="text-sm text-foreground"
                />
              ) : (
                <div className="text-sm text-foreground">-</div>
              )}
            </div>

            <InfoPanelField label={t("details.id")} icon={Hash}>
              <InfoPanelValueBox mono className="break-all">
                {instance.id}
              </InfoPanelValueBox>
            </InfoPanelField>

            <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  <Clock className="h-3 w-3 text-primary" />
                  {t("details.created")}
                </div>
                <div className="text-[13px] font-medium text-foreground">
                  {new Date(instance.created_at).toLocaleString()}
                </div>
              </div>

              <div className="space-y-1">
                <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  {t("details.updated")}
                </div>
                <div className="text-[13px] font-medium text-foreground">
                  {new Date(instance.updated_at).toLocaleString()}
                </div>
              </div>
            </div>
        </InfoPanelSection>

          {serverSpec && (
            <InfoPanelSection
              title={t("serverSpec.title")}
              contentClassName="space-y-2 text-xs"
            >
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-xs font-medium">{serverSpec.name}</div>
                  {serverSpec.version && (
                    <span className="note">v{serverSpec.version}</span>
                  )}
                </div>
                {serverSpec.description && (
                  <InfoPanelExpandableText
                    content={serverSpec.description}
                    maxLines={3}
                    textClassName="note"
                  />
                )}
              </div>
            </InfoPanelSection>
          )}
      </InfoPanelBody>
    </InfoPanelShell>
  );
}
