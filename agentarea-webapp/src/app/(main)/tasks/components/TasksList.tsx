"use client";

import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import type { TriggerCatalogEntry } from "@/app/(main)/triggers/components/triggerDisplay";
import { AgentLink } from "@/components/AgentIdentity";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { TaskItem } from "@/components/TaskItem";
import { TaskSourceBadge } from "@/components/TaskSourceBadge";
import { TaskStatus } from "@/components/TaskStatus";
import { useCurrency } from "@/hooks/useCurrency";
import { TaskWithAgent } from "@/lib/api";
import { CARD_GRID_WIDE } from "@/lib/collectionGrids";
import { formatMoney } from "@/lib/money";

interface TasksListProps {
  initialTasks: TaskWithAgent[];
  viewMode?: string;
  /** Names and draws the channel each task came from. */
  catalog?: TriggerCatalogEntry[];
  /**
   * Principal id -> display name, resolved by the caller via GET /v1/principals:
   * each task's creator, plus any principal its source names. An id missing from
   * the map is one nothing could resolve, and is rendered as unknown rather than
   * as the id.
   */
  principalNames?: Record<string, string>;
  /**
   * Drop the agent column. Set on agent-scoped listings, where every row names
   * the same agent the page is already about.
   */
  showAgent?: boolean;
}

export default function TasksList({
  initialTasks,
  viewMode = "table",
  catalog = [],
  principalNames = {},
  showAgent = true,
}: TasksListProps) {
  const t = useTranslations("TasksPage");
  const router = useRouter();
  const locale = useLocale();
  const { currency } = useCurrency();

  // Define table columns for tasks
  const taskColumns = [
    {
      accessor: "status",
      header: t("statusLabel"),
      headerClassName: "w-[140px]",
      cellClassName: "whitespace-nowrap",
      render: (value: string, row: TaskWithAgent) => (
        <div className="flex flex-col gap-1">
          <TaskStatus
            status={value}
            size="default"
            caption="auto"
            className="font-medium"
          />
          {row.scheduled_at && (
            <TableDateDisplay dateString={row.scheduled_at} />
          )}
        </div>
      ),
    },
    {
      accessor: "description",
      header: t("description"),
      headerClassName: "w-auto",
      cellClassName: "max-w-[460px]",
      render: (value: string) => (
        <p className="line-clamp-2 text-[13px] font-semibold leading-5 text-foreground">
          {value || t("noDescription")}
        </p>
      ),
    },
    ...(showAgent
      ? [
          {
            accessor: "agent_name",
            header: t("agent"),
            headerClassName: "w-[190px]",
            cellClassName: "w-[190px] max-w-[190px]",
            render: (value: string, row: TaskWithAgent) => (
              <AgentLink
                agent={{ id: row.agent_id, name: value || "Unknown Agent" }}
                size="xs"
                onClick={(event) => event.stopPropagation()}
                nameClassName="text-xs"
              />
            ),
          },
        ]
      : []),
    {
      accessor: "parameters",
      header: t("source"),
      headerClassName: "w-[180px]",
      cellClassName: "w-[180px] max-w-[180px]",
      // One column, not two: where a task came from and who it belongs to are
      // the same question asked of different task kinds. A task nobody
      // automated renders as its person; an automated one keeps its badge and
      // carries the owner in the tooltip.
      render: (value: TaskWithAgent["parameters"], row: TaskWithAgent) => (
        <TaskSourceBadge
          parameters={value}
          createdBy={row.created_by}
          principalNames={principalNames}
          catalog={catalog}
        />
      ),
    },
    {
      accessor: "total_cost",
      header: t("cost"),
      headerClassName: "w-[110px] text-right",
      cellClassName: "text-right",
      render: (value: string | number | null | undefined) => {
        const num = value != null ? Number(value) : null;
        return (
          <div className="font-mono text-xs tabular-nums text-muted-foreground">
            {num != null && !isNaN(num) ? (
              <span>{formatMoney(num, currency, locale)}</span>
            ) : (
              <span>—</span>
            )}
          </div>
        );
      },
    },
    {
      accessor: "created_at",
      header: t("created"),
      headerClassName: "w-[150px]",
      cellClassName: "whitespace-nowrap",
      render: (value: string) => <TableDateDisplay dateString={value} />,
    },
  ];

  // Render table view
  if (viewMode === "table") {
    return (
      <div>
        <Table
          className={
            showAgent
              ? "min-w-[1060px] table-fixed"
              : "min-w-[870px] table-fixed"
          }
          data={initialTasks}
          columns={taskColumns}
          onRowClick={(task) => {
            router.push(`/tasks/${task.id}`);
          }}
        />
      </div>
    );
  }

  // Render grid view (default)
  return (
    <div className={CARD_GRID_WIDE}>
      {initialTasks.map((task) => (
        <TaskItem key={task.id} task={task} />
      ))}
    </div>
  );
}
