"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Bot, Calendar, Clock } from "lucide-react";
import Table from "@/components/Table/Table";
import { TaskItem } from "@/components/TaskItem";
import { Badge } from "@/components/ui/badge";
import { TaskWithAgent } from "@/lib/browser-api";

interface TasksListProps {
  initialTasks: TaskWithAgent[];
  viewMode?: string;
}

const statusConfig = {
  running: {
    badgeVariant: "default" as const,
    label: "Running",
  },
  completed: {
    badgeVariant: "success" as const,
    label: "Completed",
  },
  success: {
    badgeVariant: "success" as const,
    label: "Success",
  },
  failed: {
    badgeVariant: "destructive" as const,
    label: "Failed",
  },
  error: {
    badgeVariant: "destructive" as const,
    label: "Error",
  },
  paused: {
    badgeVariant: "secondary" as const,
    label: "Paused",
  },
  pending: {
    badgeVariant: "secondary" as const,
    label: "Pending",
  },
};

export default function TasksList({
  initialTasks,
  viewMode = "grid",
}: TasksListProps) {
  const t = useTranslations("TasksPage");
  const router = useRouter();

  // Define table columns for tasks
  const taskColumns = [
    {
      accessor: "description",
      header: t("description") || "Description",
      render: (value: string) => (
        <span className="truncate font-medium">{value}</span>
      ),
    },
    {
      accessor: "agent_name",
      header: t("agent") || "Agent",
      render: (value: string) => (
        <div className="flex items-center gap-1.5 text-xs">
          <Bot className="h-3 w-3" />
          <span>{value || "Unknown Agent"}</span>
        </div>
      ),
    },
    {
      accessor: "status",
      header: t("status") || "Status",
      render: (value: string) => {
        const status =
          statusConfig[value as keyof typeof statusConfig] ||
          statusConfig.pending;
        return (
          <Badge variant={status.badgeVariant} className="whitespace-nowrap">
            {status.label}
          </Badge>
        );
      },
    },
    {
      accessor: "created_at",
      header: t("created") || "Created",
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
    <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
      {initialTasks.map((task) => (
        <TaskItem key={task.id} task={task} />
      ))}
    </div>
  );
}
