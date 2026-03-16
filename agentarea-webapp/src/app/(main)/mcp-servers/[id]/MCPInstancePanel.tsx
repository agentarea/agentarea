"use client";

import { useTranslations } from "next-intl";
import { Clock, Hash } from "lucide-react";
import ExpandableText from "@/components/TaskInfoPanel/components/ExpandableText";
import Section from "@/components/TaskInfoPanel/components/Section";
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
    <div className="h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700">
      <div className="min-h-full bg-white dark:bg-zinc-800">
        <MCPInstanceInfoHeader instance={instance} />

        <div className="space-y-4 px-3.5 py-3 text-xs">
          <Section title={t("details.title")} contentClassName="space-y-3 text-xs">
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
                <ExpandableText
                  content={instance.description}
                  maxLines={3}
                  textClassName="text-sm text-foreground"
                />
              ) : (
                <div className="text-sm text-foreground">-</div>
              )}
            </div>

            <div className="space-y-1">
              <div className="flex items-center gap-1.5 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                <Hash className="h-3 w-3 text-primary" />
                {t("details.id")}
              </div>
              <div className="break-all rounded-md border border-border/50 bg-muted/30 p-1.5 font-mono text-xs text-foreground">
                {instance.id}
              </div>
            </div>

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
          </Section>

          {serverSpec && (
            <Section title={t("serverSpec.title")} contentClassName="space-y-2 text-xs">
              <div className="space-y-1">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-xs font-medium">{serverSpec.name}</div>
                  {serverSpec.version && (
                    <span className="note">v{serverSpec.version}</span>
                  )}
                </div>
                {serverSpec.description && (
                  <ExpandableText
                    content={serverSpec.description}
                    maxLines={3}
                    textClassName="note"
                  />
                )}
              </div>
            </Section>
          )}
        </div>
      </div>
    </div>
  );
}
