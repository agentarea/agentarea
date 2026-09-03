"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { AgentLink } from "@/components/AgentIdentity";
import Table from "@/components/Table/Table";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { TaskItem } from "@/components/TaskItem";
import { TaskSourceBadge } from "@/components/TaskSourceBadge";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { TaskWithAgent } from "@/lib/api";
import { CARD_GRID_WIDE } from "@/lib/collectionGrids";
import { getTaskStatusPresentation } from "@/lib/status";

interface TasksListProps {
  initialTasks: TaskWithAgent[];
  viewMode?: string;
}

function formatUsdCost(value: number) {
  return `$${value.toFixed(4)}`;
}

export default function TasksList({
  initialTasks,
  viewMode = "grid",
}: TasksListProps) {
  const t = useTranslations("TasksPage");
  const tStatus = useTranslations("TasksPage.status");
  const router = useRouter();

  // Define table columns for tasks
  const taskColumns = [
    {
      accessor: "status",
      header: t("statusLabel"),
      headerClassName: "w-[140px]",
      cellClassName: "whitespace-nowrap",
      render: (value: string, row: TaskWithAgent) => {
        const presentation = getTaskStatusPresentation(value);
        const label = presentation.labelKey
          ? tStatus(presentation.labelKey)
          : presentation.label;

        return (
          <div className="flex flex-col gap-1">
            <StatusIndicator
              size="default"
              tone={presentation.tone}
              pulse={presentation.pulse}
              className="font-medium"
            >
              {label}
            </StatusIndicator>
            {row.scheduled_at && (
              <TableDateDisplay dateString={row.scheduled_at} />
            )}
          </div>
        );
      },
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
    {
      accessor: "parameters",
      header: t("source"),
      headerClassName: "w-[160px]",
      cellClassName: "w-[160px] max-w-[160px]",
      render: (value: TaskWithAgent["parameters"]) => (
        <TaskSourceBadge parameters={value} />
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
              <span>{formatUsdCost(num)}</span>
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
          className="min-w-[1040px] table-fixed"
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
