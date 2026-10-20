"use client";

import { useState } from "react";
import { useFormatter, useLocale, useTranslations } from "next-intl";
import { ArrowUpRight, Check, Copy } from "lucide-react";
import type { TriggerExecutionResponse } from "@/api/client/types.gen";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { TableRowAction } from "@/components/Table/TableRowAction";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { getTriggerExecutionStatusPresentation } from "@/lib/status";
import { formatTriggerCost } from "../../components/triggerDisplay";

interface ExecutionsTableProps {
  executions: TriggerExecutionResponse[];
  /** Principal id -> display name, resolved by the page via GET /v1/principals. */
  principalNames?: Record<string, string>;
  /** The workspace's billing currency, loaded by the page as the overview does. */
  currency: string | null;
}

/**
 * An id is only worth anything copied whole, so it is not a column: a row's
 * hover action puts it on the clipboard.
 */
function CopyIdAction({ id }: { id: string }) {
  const t = useTranslations("TriggersPage.detail");
  const [copied, setCopied] = useState(false);
  return (
    <TableRowAction
      variant="ghost"
      icon={copied ? <Check /> : <Copy />}
      title={id}
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(id);
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        } catch (error) {
          console.error("Failed to copy execution id", error);
        }
      }}
    >
      {copied ? t("idCopied") : t("copyExecutionId")}
    </TableRowAction>
  );
}

function OpenTaskAction({ taskId }: { taskId: string }) {
  const t = useTranslations("TriggersPage.detail");
  const router = useWorkspaceRouter();
  return (
    <TableRowAction
      variant="ghost"
      icon={<ArrowUpRight />}
      onClick={() => router.push(`/tasks/${taskId}`)}
    >
      {t("openTask")}
    </TableRowAction>
  );
}

export default function ExecutionsTable({
  executions,
  principalNames = {},
  currency,
}: ExecutionsTableProps) {
  const t = useTranslations("TriggersPage.detail");
  const format = useFormatter();
  const locale = useLocale();
  const fmtCost = (value: number) => formatTriggerCost(value, currency, locale);
  // Seconds below a minute, minutes above: "12.4 s", "2 min", in the UI locale.
  const fmtDuration = (ms: number) =>
    ms < 60_000
      ? format.number(ms / 1000, {
          style: "unit",
          unit: "second",
          unitDisplay: "short",
          maximumFractionDigits: 1,
        })
      : format.number(ms / 60_000, {
          style: "unit",
          unit: "minute",
          unitDisplay: "short",
          maximumFractionDigits: 1,
        });

  const columns = [
    {
      accessor: "status",
      header: t("columnStatus"),
      headerClassName: "w-[220px]",
      cellClassName: "w-[220px] max-w-[220px]",
      // What went wrong sits under the status it explains, not in a column of
      // its own that is empty for every run that worked.
      render: (value: unknown, row?: TriggerExecutionResponse) => {
        const status = getTriggerExecutionStatusPresentation(
          (value as string) || "unknown"
        );
        return (
          <div className="flex min-w-0 flex-col gap-1">
            <StatusIndicator
              kind={status.kind}
              className="whitespace-nowrap font-medium"
            >
              {status.labelKey
                ? t(`executionStatus.${status.labelKey}`)
                : status.label}
            </StatusIndicator>
            {row?.error_message && (
              <p
                className="truncate text-xs text-muted-foreground"
                title={row.error_message}
              >
                {row.error_message}
              </p>
            )}
          </div>
        );
      },
    },
    {
      accessor: "executed_at",
      header: t("columnStarted"),
      headerClassName: "w-[160px]",
      cellClassName: "w-[160px]",
      render: (value: unknown) => (
        <TableDateDisplay dateString={value as string} relative />
      ),
    },
    {
      accessor: "fired_by",
      header: t("executionSource"),
      headerClassName: "hidden w-[200px] md:table-cell",
      cellClassName: "hidden max-w-[200px] md:table-cell",
      // Empty means the trigger fired itself -- the schedule came due, or the
      // webhook was called. A name means a person asked for this one run.
      render: (value: unknown) => {
        const firedBy = value as string | null;
        return (
          <span className="block truncate text-xs text-muted-foreground">
            {firedBy
              ? principalNames[firedBy]
                ? `${t("executionManual")} · ${principalNames[firedBy]}`
                : t("executionManual")
              : t("executionAutomatic")}
          </span>
        );
      },
    },
    {
      accessor: "execution_time_ms",
      header: t("columnDuration"),
      headerClassName: "hidden w-[110px] text-right md:table-cell",
      cellClassName: "hidden text-right md:table-cell",
      render: (value: unknown) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {value != null ? fmtDuration(value as number) : "—"}
        </span>
      ),
    },
    {
      accessor: "cost_usd",
      header: t("cost"),
      headerClassName: "w-[100px] text-right",
      cellClassName: "text-right",
      // Null means the run created no task, or the task has not reported a
      // cost yet — different from a run that genuinely cost nothing.
      render: (value: unknown) => (
        <span className="font-mono text-xs tabular-nums text-muted-foreground">
          {value != null ? fmtCost(value as number) : "—"}
        </span>
      ),
    },
    {
      // The row's actions, revealed on hover as in the other tables (API
      // keys, secrets): the same link on every row was a column of repeats.
      accessor: "actions",
      header: "",
      headerClassName: "w-0",
      cellClassName: "whitespace-nowrap text-right",
      render: (_: unknown, row?: TriggerExecutionResponse) =>
        row ? (
          <div className="flex justify-end gap-1">
            {row.task_id && <OpenTaskAction taskId={row.task_id} />}
            <CopyIdAction id={row.id} />
          </div>
        ) : null,
    },
  ];

  return <Table data={executions} columns={columns} />;
}
