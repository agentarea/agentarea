"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  AlertCircle,
  CheckCircle,
  FileText,
  Pause,
  Play,
  Square,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  cancelAgentTask,
  getAgentTaskStatus,
  listAgentTasks,
  pauseAgentTask,
  resumeAgentTask,
} from "@/lib/browser-api";
import { TaskStatus, TaskWithStatus } from "../types";

interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_id: string;
}

interface AgentTasksListProps {
  agentId: string;
  initialTasks?: TaskWithStatus[];
}

export default function AgentTasksList({
  agentId,
  initialTasks = [],
}: AgentTasksListProps) {
  const [tasks, setTasks] = useState<Task[]>(initialTasks);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>(
    // Initialize with statuses from initialTasks if available
    initialTasks.reduce(
      (acc, task) => {
        if (task.taskStatus) {
          acc[task.id] = task.taskStatus;
        }
        return acc;
      },
      {} as Record<string, TaskStatus>
    )
  );

  useEffect(() => {
    // Only fetch if we don't have initial data
    if (initialTasks.length === 0) {
      loadTasks();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agentId]);

  const loadTasks = async () => {
    setTasksLoading(true);
    try {
      const { data: tasksData, error } = await listAgentTasks(agentId);
      if (!error && tasksData) {
        setTasks(tasksData);
        for (const task of tasksData) {
          void loadTaskStatus(task.id);
        }
      }
    } catch (error) {
      console.error("Failed to load tasks:", error);
    } finally {
      setTasksLoading(false);
    }
  };

  const loadTaskStatus = async (taskId: string) => {
    try {
      const { data: statusData, error } = await getAgentTaskStatus(
        agentId,
        taskId
      );
      if (!error && statusData) {
        setTaskStatuses((prev) => ({
          ...prev,
          [taskId]: statusData as TaskStatus,
        }));
      }
    } catch (error) {
      console.error(`Failed to load status for task ${taskId}:`, error);
    }
  };

  const handleTaskAction = async (
    taskId: string,
    action: "pause" | "resume" | "cancel"
  ) => {
    try {
      let result;
      switch (action) {
        case "pause":
          result = await pauseAgentTask(agentId, taskId);
          break;
        case "resume":
          result = await resumeAgentTask(agentId, taskId);
          break;
        case "cancel":
          result = await cancelAgentTask(agentId, taskId);
          break;
      }

      if (!result.error) {
        void loadTaskStatus(taskId);
        void loadTasks();
      }
    } catch (error) {
      console.error(`Failed to ${action} task:`, error);
    }
  };

  return (
    <div className="h-full space-y-2 overflow-auto">
      {tasksLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="flex items-center gap-2">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
            <span className="text-sm text-gray-500">Loading tasks...</span>
          </div>
        </div>
      ) : tasks.length === 0 ? (
        <div className="rounded-lg border border-gray-200 bg-white py-8 text-center">
          <div className="mx-auto mb-3 flex h-8 w-8 items-center justify-center rounded bg-gray-100">
            <CheckCircle className="h-4 w-4 text-gray-400" />
          </div>
          <h3 className="mb-1 font-medium text-gray-900">No tasks yet</h3>
          <p className="mb-4 text-sm text-gray-500">
            This agent hasn&apos;t been assigned any tasks yet.
          </p>
          <Link href={`./new`}>
            <Button size="sm" className="gap-2">
              Create your first task
            </Button>
          </Link>
        </div>
      ) : (
        <div className="space-y-2">
          {tasks.map((task) => {
            const status = taskStatuses[task.id];
            const isActive = ["running", "paused"].includes(task.status);

            return (
              <div
                key={task.id}
                className="rounded border border-gray-200 bg-white p-3 transition-colors hover:border-gray-300"
              >
                <div className="flex items-start justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="mb-1 flex items-center gap-2">
                      <Badge
                        variant="secondary"
                        className={`px-2 py-0.5 text-xs ${
                          task.status === "completed"
                            ? "border-green-200 bg-green-50 text-green-700"
                            : task.status === "running"
                              ? "border-blue-200 bg-blue-50 text-blue-700"
                              : task.status === "failed"
                                ? "border-red-200 bg-red-50 text-red-700"
                                : "border-gray-200 bg-gray-50 text-gray-700"
                        }`}
                      >
                        {task.status}
                      </Badge>
                      <span className="text-xs text-gray-500">
                        {new Date(task.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="mb-1 truncate text-sm font-medium text-gray-900">
                      {task.description}
                    </p>
                    {status?.error && (
                      <div className="flex items-center gap-1 text-xs text-red-600">
                        <AlertCircle className="h-3 w-3" />
                        <span className="truncate">{status.error}</span>
                      </div>
                    )}
                  </div>
                  <div className="ml-3 flex flex-shrink-0 gap-1">
                    {task.status === "running" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleTaskAction(task.id, "pause")}
                        className="h-7 px-2"
                      >
                        <Pause className="h-3 w-3" />
                      </Button>
                    )}
                    {task.status === "paused" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleTaskAction(task.id, "resume")}
                        className="h-7 px-2"
                      >
                        <Play className="h-3 w-3" />
                      </Button>
                    )}
                    {isActive && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleTaskAction(task.id, "cancel")}
                        className="h-7 px-2"
                      >
                        <Square className="h-3 w-3" />
                      </Button>
                    )}
                    <Link href={`/tasks/${task.id}`}>
                      <Button size="sm" variant="ghost" className="h-7 px-2">
                        <FileText className="h-3 w-3" />
                      </Button>
                    </Link>
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
