"use client";

import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { CheckCircle2, XCircle } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import Table, { type Column } from "@/components/Table/Table";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerStatusPresentation } from "@/lib/status";
import {
  describeTriggerSchedule,
  findTriggerCatalogEntry,
  formatCompactDistance,
  getTriggerDisplayName,
  getTriggerHealth,
  TriggerSourceMark,
  type EnrichedTrigger,
  type TriggerCatalogEntry,
} from "./triggerDisplay";

interface TriggersTableProps {
  triggers: EnrichedTrigger[];
  catalog?: TriggerCatalogEntry[];
  /** Grouped view already names the channel in the section header. */
  hideChannelColumn?: boolean;
}

export default function TriggersTable({
  triggers,
  catalog = [],
  hideChannelColumn = false,
}: TriggersTableProps) {
  const t = useTranslations("TriggersPage.table");
  const tStatus = useTranslations("TriggersPage.status");
  const router = useWorkspaceRouter();

  const columns: Column<EnrichedTrigger>[] = [
    // Leads the row: the icon belongs to the event source, which is what this
    // column spells out ("On GitHub event"), not to the trigger's own name.
    {
      header: t("when"),
      accessor: "when",
      headerClassName: "w-[200px]",
      render: (_value, trigger) => {
        if (!trigger) return null;
        const entry = findTriggerCatalogEntry(trigger, catalog);
        return (
          <span className="flex min-w-0 items-center gap-2.5">
            <TriggerSourceMark entry={entry} trigger={trigger} size={28} />
            <span className="truncate text-[13px] text-muted-foreground">
              {describeTriggerSchedule(trigger)}
            </span>
          </span>
        );
      },
    },
    {
      header: t("name"),
      accessor: "name",
      headerClassName: "w-[320px]",
      render: (_value, trigger) =>
        trigger ? (
          <span className="block truncate text-[13px] font-medium text-foreground group-hover:text-primary">
            {trigger.name}
          </span>
        ) : null,
    },
    ...(hideChannelColumn
      ? []
      : [
          {
            header: t("channel"),
            accessor: "channel",
            headerClassName: "hidden w-[150px] sm:table-cell",
            cellClassName: "hidden sm:table-cell",
            render: (_value, trigger) =>
              trigger ? (
                <span className="block truncate text-[13px] text-muted-foreground">
                  {getTriggerDisplayName(
                    trigger,
                    findTriggerCatalogEntry(trigger, catalog)
                  )}
                </span>
              ) : null,
          } satisfies Column<EnrichedTrigger>,
        ]),
    {
      header: t("agent"),
      accessor: "agent_name",
      headerClassName: "hidden w-[170px] md:table-cell",
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
      headerClassName: "hidden w-[130px] lg:table-cell",
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
      headerClassName: "hidden w-[120px] xl:table-cell",
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
      headerClassName: "w-[120px]",
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
    // Fixed layout, not auto: the grouped view renders one table per channel,
    // and content-derived widths would make each group's columns land in a
    // different place.
    <Table
      className="table-fixed"
      data={triggers}
      columns={columns}
      onRowClick={(trigger) => router.push(`/triggers/${trigger.id}`)}
    />
  );
}
