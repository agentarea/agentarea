"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { CheckCircle2, XCircle } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import Table, { type Column } from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import {
  describeTriggerSchedule,
  findTriggerCatalogEntry,
  formatCompactDistance,
  getTriggerDisplayName,
  getTriggerHealth,
  renderTriggerIcon,
  type EnrichedTrigger,
  type TriggerCatalogEntry,
} from "./triggerDisplay";

interface TriggersTableProps {
  triggers: EnrichedTrigger[];
  catalog?: TriggerCatalogEntry[];
  hideChannelColumn?: boolean;
}

export default function TriggersTable({
  triggers,
  catalog = [],
  hideChannelColumn = false,
}: TriggersTableProps) {
  const t = useTranslations("TriggersPage.table");
  const tStatus = useTranslations("TriggersPage.status");
  const router = useRouter();

  const columns: Column<EnrichedTrigger>[] = [
    {
      header: t("name"),
      accessor: "name",
      render: (_value, trigger) => {
        if (!trigger) return null;
        const entry = findTriggerCatalogEntry(trigger, catalog);
        const isCron = trigger.trigger_type === "cron";
        return (
          <span className="flex min-w-0 items-center gap-2.5">
            <span
              className={cn(
                "flex h-7 w-7 shrink-0 items-center justify-center rounded-md",
                isCron
                  ? "bg-primary/10 text-primary"
                  : "bg-violet-100 text-violet-600 dark:bg-violet-950/40 dark:text-violet-400"
              )}
            >
              {renderTriggerIcon(entry, trigger, "h-3.5 w-3.5")}
            </span>
            <span className="truncate text-[13px] font-medium text-foreground group-hover:text-primary">
              {trigger.name}
            </span>
          </span>
        );
      },
    },
    ...(hideChannelColumn
      ? []
      : [
          {
            header: t("channel"),
            accessor: "channel",
            headerClassName: "hidden sm:table-cell",
            cellClassName: "hidden sm:table-cell",
            render: (_value, trigger) =>
              trigger ? (
                <span className="text-[13px] text-muted-foreground">
                  {getTriggerDisplayName(
                    trigger,
                    findTriggerCatalogEntry(trigger, catalog)
                  )}
                </span>
              ) : null,
          } satisfies Column<EnrichedTrigger>,
        ]),
    {
      header: t("when"),
      accessor: "when",
      headerClassName: "hidden md:table-cell",
      cellClassName: "hidden md:table-cell",
      render: (_value, trigger) =>
        trigger ? (
          <span className="text-[13px] text-muted-foreground">
            {describeTriggerSchedule(trigger)}
          </span>
        ) : null,
    },
    {
      header: t("agent"),
      accessor: "agent_name",
      headerClassName: "hidden md:table-cell",
      cellClassName: "hidden md:table-cell",
      render: (_value, trigger) =>
        trigger ? (
          <span className="flex min-w-0 items-center gap-2">
            {trigger.agent_name && (
              <AgentAvatar
                agent={{
                  id: trigger.agent_id || trigger.agent_name,
                  name: trigger.agent_name,
                }}
                size="xs"
              />
            )}
            <span className="truncate text-[13px] text-muted-foreground">
              {trigger.agent_name || "—"}
            </span>
          </span>
        ) : null,
    },
    {
      header: t("lastRun"),
      accessor: "last_run",
      headerClassName: "hidden lg:table-cell",
      cellClassName: "hidden lg:table-cell",
      render: (_value, trigger) => {
        if (!trigger?.last_execution_at) {
          return <span className="text-[13px] text-muted-foreground/60">—</span>;
        }
        const failing = Number(trigger.consecutive_failures ?? 0) > 0;
        return (
          <span className="flex items-center gap-1 text-[13px] text-muted-foreground">
            {failing ? (
              <XCircle className="h-3.5 w-3.5 text-red-500" />
            ) : (
              <CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" />
            )}
            {formatCompactDistance(trigger.last_execution_at)}
          </span>
        );
      },
    },
    {
      header: t("created"),
      accessor: "created",
      headerClassName: "hidden xl:table-cell",
      cellClassName: "hidden xl:table-cell",
      render: (_value, trigger) =>
        trigger?.created_at ? (
          <span className="text-[13px] text-muted-foreground">
            {formatCompactDistance(trigger.created_at)}
          </span>
        ) : (
          <span className="text-[13px] text-muted-foreground/60">—</span>
        ),
    },
    {
      header: t("status"),
      accessor: "status",
      render: (_value, trigger) => {
        if (!trigger) return null;
        const health = getTriggerHealth(trigger);
        const status = getTriggerStatusPresentation(health);
        return (
          <StatusIndicator size="sm" tone={status.tone} pulse={status.pulse}>
            {tStatus(health)}
          </StatusIndicator>
        );
      },
    },
  ];

  return (
    <Table
      data={triggers}
      columns={columns}
      onRowClick={(trigger) => router.push(`/triggers/${trigger.id}`)}
    />
  );
}
