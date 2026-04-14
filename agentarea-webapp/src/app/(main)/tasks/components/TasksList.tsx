"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Bot, Calendar, Clock, DollarSign, GitFork } from "lucide-react";
import Table from "@/components/Table/Table";
import { TaskItem } from "@/components/TaskItem";
import { Badge } from "@/components/ui/badge";
import { TaskWithAgent } from "@/lib/api";

interface TasksListProps {
  initialTasks: TaskWithAgent[];
  viewMode?: string;
}

const statusVariants = {
  running: "default",
  completed: "success",
  success: "success",
  failed: "destructive",
  blocked: "secondary",
  error: "destructive",
  paused: "secondary",
  pending: "secondary",
} as const;

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
        const isDelegation = (row as any).parameters?.source === "agent_delegation";
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
      render: (value: string) => (
        <div className="flex items-center gap-1.5 text-xs">
          <Bot className="h-3 w-3" />
          <span>{value || "Unknown Agent"}</span>
        </div>
      ),
    },
    {
      accessor: "status",
      header: t("statusLabel"),
      render: (value: string) => {
        const variant =
          statusVariants[value as keyof typeof statusVariants] || "secondary";
        // Check if translation exists, otherwise fallback to capitalized value
        const label = ["running", "completed", "success", "failed", "blocked", "error", "paused", "pending"].includes(value)
          ? tStatus(value)
          : value.charAt(0).toUpperCase() + value.slice(1);
          
        return (
          <Badge variant={variant} className="whitespace-nowrap">
            {label}
          </Badge>
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
              <>
                <DollarSign className="h-3 w-3" />
                <span className="font-mono">{num.toFixed(4)}</span>
              </>
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

  const totalCost = initialTasks.reduce((sum, t) => sum + (Number((t as any).total_cost) || 0), 0);

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
        {totalCost > 0 && (
          <div className="flex items-center justify-end gap-2 border-t px-4 py-2 text-sm">
            <span className="text-muted-foreground">Total:</span>
            <span className="flex items-center gap-1 font-mono font-semibold">
              <DollarSign className="h-3.5 w-3.5" />
              {totalCost.toFixed(4)}
            </span>
          </div>
        )}
      </div>
    );
  }

  // Render grid view (default)
  return (
    <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5">
      {initialTasks.map((task) => (
        <TaskItem key={task.id} task={task} />
      ))}
    </div>
  );
}
