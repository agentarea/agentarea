"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Calendar, Clock, GitFork } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import Table from "@/components/Table/Table";
import { TaskItem } from "@/components/TaskItem";
import { TaskWithAgent } from "@/lib/api";
import { CARD_GRID_WIDE } from "@/lib/collectionGrids";
import { getTaskStatusPresentation } from "@/lib/status";
import { StatusIndicator } from "@/components/ui/status-indicator";

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
      accessor: "description",
      header: t("description"),
      render: (value: string, row: TaskWithAgent) => {
        const isDelegation =
          (row as any).parameters?.source === "agent_delegation";
        return (
          <div className="flex items-center gap-2 max-w-[300px]">
            {isDelegation && (
              <GitFork className="h-3.5 w-3.5 shrink-0 text-primary" />
            )}
            <span className="line-clamp-2 font-medium">{value}</span>
          </div>
        );
      },
    },
    {
      accessor: "agent_name",
      header: t("agent"),
      render: (value: string, row: TaskWithAgent) => (
        <div className="flex items-center gap-1.5 text-xs">
          <AgentAvatar
            agent={{ id: row.agent_id || value || "agent", name: value }}
            size="xs"
          />
          <span>{value || "Unknown Agent"}</span>
        </div>
      ),
    },
    {
      accessor: "status",
      header: t("statusLabel"),
      render: (value: string) => {
        const presentation = getTaskStatusPresentation(value);
        const label = presentation.labelKey
          ? tStatus(presentation.labelKey)
          : presentation.label;

        return (
          <StatusIndicator
            size="sm"
            tone={presentation.tone}
            pulse={presentation.pulse}
            className="whitespace-nowrap"
          >
            {label}
          </StatusIndicator>
        );
      },
    },
    {
      accessor: "total_cost",
      header: t("cost"),
      render: (value: string | number | null | undefined) => {
        const num = value != null ? Number(value) : null;
        return (
          <div className="flex items-center gap-1 text-xs text-muted-foreground">
            {num != null && !isNaN(num) ? (
              <span className="font-mono">{formatUsdCost(num)}</span>
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
      render: (value: string) => (
        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Calendar className="h-3 w-3" />
            <span>
              {new Date(value).toLocaleDateString("en", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3" />
            <span>
              {new Date(value).toLocaleTimeString("ru-RU", {
                hour: "2-digit",
                minute: "2-digit",
              })}
            </span>
          </div>
        </div>
      ),
    },
  ];

  // Render table view
  if (viewMode === "table") {
    return (
      <div>
        <Table
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
