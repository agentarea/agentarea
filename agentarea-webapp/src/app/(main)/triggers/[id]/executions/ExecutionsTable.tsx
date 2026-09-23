"use client";

import { formatDistanceToNow } from "date-fns";
import { useTranslations } from "next-intl";
import type { TriggerExecutionResponse } from "@/api/client/types.gen";
import Table from "@/components/Table/Table";
import { Badge } from "@/components/ui/badge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTriggerExecutionStatusPresentation } from "@/lib/status";
import { formatTriggerCost as fmtUsd } from "../../components/triggerDisplay";

interface ExecutionsTableProps {
  executions: TriggerExecutionResponse[];
  triggerId: string;
  currentPage: number;
  /** Principal id -> display name, resolved by the page via GET /v1/principals. */
  principalNames?: Record<string, string>;
}

export default function ExecutionsTable({
  executions,
  triggerId: _triggerId,
  currentPage: _currentPage,
  principalNames = {},
}: ExecutionsTableProps) {
  const t = useTranslations("TriggersPage.detail");
  const columns = [
    {
      accessor: "id",
      header: "Execution ID",
      render: (value: string) => (
        <span className="font-mono text-xs">{value?.slice(0, 8)}...</span>
      ),
    },
    {
      accessor: "status",
      header: "Status",
      render: (value: string) => {
        const status = getTriggerExecutionStatusPresentation(value || "unknown");

        return (
          <StatusIndicator
            size="sm"
            tone={status.tone}
            pulse={status.pulse}
            className="whitespace-nowrap"
          >
            {status.label}
          </StatusIndicator>
        );
      },
    },
    {
      accessor: "fired_by",
      header: t("executionSource"),
      // Empty means the trigger fired itself -- the schedule came due, or the
      // webhook was called. A name means a person asked for this one run.
      render: (value: string | null) =>
        value ? (
          <Badge variant="zinc" size="sm">
            {principalNames[value]
              ? `${t("executionManual")} · ${principalNames[value]}`
              : t("executionManual")}
          </Badge>
        ) : (
          <span className="text-muted-foreground">{t("executionAutomatic")}</span>
        ),
    },
    {
      accessor: "executed_at",
      header: "Executed",
      render: (value: string) => (
        <span className="text-muted-foreground">
          {value
            ? formatDistanceToNow(new Date(value), { addSuffix: true })
            : "-"}
        </span>
      ),
    },
    {
      accessor: "execution_time_ms",
      header: "Duration",
      render: (value: number) => (
        <span className="text-muted-foreground">
          {value != null ? `${value}ms` : "-"}
        </span>
      ),
    },
    {
      accessor: "cost_usd",
      header: t("cost"),
      // Null means the run created no task, or the task has not reported a
      // cost yet — different from a run that genuinely cost nothing.
      render: (value: number | null) => (
        <span className="tabular-nums text-muted-foreground">
          {value != null ? fmtUsd(value) : "-"}
        </span>
      ),
    },
    {
      accessor: "task_id",
      header: "Task",
      render: (value: string) => (
        <span className="font-mono text-xs text-muted-foreground">
          {value ? `${value.slice(0, 8)}...` : "-"}
        </span>
      ),
    },
    {
      accessor: "error_message",
      header: "Error",
      render: (value: string) => (
        <span className="max-w-xs truncate text-muted-foreground block text-xs">
          {value || "-"}
        </span>
      ),
    },
  ];

  return <Table data={executions} columns={columns} />;
}
