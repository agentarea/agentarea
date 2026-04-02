"use client";

import { useTranslations } from "next-intl";
import { Bot, Layers } from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { TaskStatusIcon } from "@/components/ui/task-status-icon";
import { TaskWithAgent } from "@/lib/api";
import { cn } from "@/lib/utils";

interface TaskDetailsCardProps {
  task: {
    agent_id: string;
    agent_name?: string;
    agent_description?: string;
    created_at: string;
    execution_id?: string | null;
  };
  currentStatus: string;
  startTime: string;
  endTime?: string;
  executionTime: string;
}

export default function TaskDetailsCard({
  task,
  currentStatus,
  startTime,
  endTime,
  executionTime,
}: TaskDetailsCardProps) {
  const t = useTranslations("TaskDetailsCard");
  const tStatus = useTranslations("TasksPage.status");
  const status = currentStatus as TaskWithAgent["status"];

  const label = [
    "running",
    "completed",
    "success",
    "failed",
    "error",
    "paused",
    "pending",
  ].includes(status)
    ? tStatus(status)
    : status.charAt(0).toUpperCase() + status.slice(1);

  const colorClass =
    {
      completed: "text-green-600 dark:text-green-500",
      success: "text-green-600 dark:text-green-500",
      failed: "text-red-600 dark:text-red-500",
      error: "text-red-600 dark:text-red-500",
      running: "text-primary",
      in_progress: "text-primary",
      pending: "text-muted-foreground",
      paused: "text-muted-foreground",
    }[status] || "text-muted-foreground";

  return (
    <Card className="shadow-sm">
      <CardHeader className="pb-3">
        <div className="flex items-center gap-2">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
            <Layers className="h-4 w-4 text-primary" />
          </div>
          <div>
            <CardTitle className="text-base">{t("title")}</CardTitle>
            <CardDescription className="text-xs">
              {t("description")}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Compact Status */}
        <div className="flex items-center justify-between rounded-lg border bg-gray-50 p-2 dark:bg-gray-800">
          <div className="flex items-center gap-2">
            <TaskStatusIcon status={status} className="h-5 w-5 shrink-0" />
            <div>
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {t("status")}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-1.5 ml-2">
            <span
              className={cn(
                "text-[11px] font-normal uppercase tracking-wider",
                colorClass
              )}
            >
              {label}
            </span>
          </div>
        </div>

        {/* Compact Agent Info */}
        <div className="rounded-lg border bg-gray-50 p-2 dark:bg-gray-800">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded bg-blue-50 dark:bg-blue-900/30">
              <Bot className="h-3 w-3 text-blue-600" />
            </div>
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                {task.agent_name || `Agent ${task.agent_id}`}
              </p>
              <p className="truncate text-xs text-gray-600 dark:text-gray-400">
                {task.agent_description || t("noDescription")}
              </p>
            </div>
          </div>
        </div>

        {/* Compact Timing Information */}
        <div className="space-y-1">
          <div className="flex items-center justify-between text-xs">
            <span className="text-gray-600 dark:text-gray-400">
              {t("created")}
            </span>
            <span className="font-medium text-gray-900 dark:text-gray-100">
              {new Date(task.created_at).toLocaleDateString()}
            </span>
          </div>
          {startTime && startTime !== task.created_at && (
            <div className="flex items-center justify-between text-xs">
              <span className="text-gray-600 dark:text-gray-400">
                {t("started")}
              </span>
              <span className="font-medium text-gray-900 dark:text-gray-100">
                {new Date(startTime).toLocaleDateString()}
              </span>
            </div>
          )}
          {endTime && (
            <>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-600 dark:text-gray-400">
                  {t("completed")}
                </span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {new Date(endTime).toLocaleDateString()}
                </span>
              </div>
              <div className="flex items-center justify-between text-xs">
                <span className="text-gray-600 dark:text-gray-400">
                  {t("duration")}
                </span>
                <span className="font-medium text-gray-900 dark:text-gray-100">
                  {executionTime}
                </span>
              </div>
            </>
          )}
        </div>

        {task.execution_id && (
          <div className="rounded bg-gray-50 p-2 dark:bg-gray-700">
            <p className="mb-0.5 text-xs text-gray-600 dark:text-gray-400">
              {t("executionId")}
            </p>
            <code className="break-all font-mono text-xs text-gray-900 dark:text-gray-100">
              {task.execution_id}
            </code>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
