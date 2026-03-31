"use client";

import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Bot, Calendar, Clock } from "lucide-react";
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
      cellClassName: "max-w-[300px]",
      render: (value: string) => (
        <span className="block truncate font-medium">{value}</span>
      ),
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
        const label = [
          "running",
          "completed",
          "success",
          "failed",
          "error",
          "paused",
          "pending",
        ].includes(value)
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
      accessor: "created_at",
      header: t("created"),
      render: (value: string) => (
        <div className="flex flex-col gap-1 text-xs text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Calendar className="h-3 w-3 shrink-0" />
            <span className="whitespace-nowrap">
              {new Date(value).toLocaleDateString("en", {
                day: "numeric",
                month: "short",
                year: "numeric",
              })}
            </span>
          </div>
          <div className="flex items-center gap-1.5">
            <Clock className="h-3 w-3 shrink-0" />
            <span className="whitespace-nowrap">
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
      <Table
        data={initialTasks}
        columns={taskColumns}
        onRowClick={(task) => {
          router.push(`/tasks/${task.id}`);
        }}
      />
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
