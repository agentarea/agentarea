"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";
import {
  listAgentTasks,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  cancelAgentTask,
} from "@/lib/browser-api";
import { AlertCircle, CheckCircle, FileText, Pause, Play, Square } from "lucide-react";
import { TaskWithStatus, TaskStatus } from "../types";

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

export default function AgentTasksList({ agentId, initialTasks = [] }: AgentTasksListProps) {
  const [tasks, setTasks] = useState<Task[]>(initialTasks);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>(
    // Initialize with statuses from initialTasks if available
    initialTasks.reduce((acc, task) => {
      if (task.taskStatus) {
        acc[task.id] = task.taskStatus;
      }
      return acc;
    }, {} as Record<string, TaskStatus>)
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
      const { data: statusData, error } = await getAgentTaskStatus(agentId, taskId);
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

  const handleTaskAction = async (taskId: string, action: "pause" | "resume" | "cancel") => {
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
    <div className="space-y-2 h-full overflow-auto">
      {tasksLoading ? (
        <div className="flex items-center justify-center py-8">
          <div className="flex items-center gap-2">
            <div className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-sm text-gray-500">Loading tasks...</span>
          </div>
        </div>
      ) : tasks.length === 0 ? (
        <div className="text-center py-8 bg-white border border-gray-200 rounded-lg">
          <div className="h-8 w-8 bg-gray-100 rounded flex items-center justify-center mx-auto mb-3">
            <CheckCircle className="h-4 w-4 text-gray-400" />
          </div>
          <h3 className="font-medium text-gray-900 mb-1">No tasks yet</h3>
          <p className="text-sm text-gray-500 mb-4">
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
                className="bg-white border border-gray-200 rounded p-3 hover:border-gray-300 transition-colors"
              >
                <div className="flex items-start justify-between">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1">
                      <Badge
                        variant="secondary"
                        className={`text-xs px-2 py-0.5 ${
                          task.status === "completed"
                            ? "bg-green-50 text-green-700 border-green-200"
                            : task.status === "running"
                            ? "bg-blue-50 text-blue-700 border-blue-200"
                            : task.status === "failed"
                            ? "bg-red-50 text-red-700 border-red-200"
                            : "bg-gray-50 text-gray-700 border-gray-200"
                        }`}
                      >
                        {task.status}
                      </Badge>
                      <span className="text-xs text-gray-500">
                        {new Date(task.created_at).toLocaleDateString()}
                      </span>
                    </div>
                    <p className="font-medium text-gray-900 text-sm mb-1 truncate">{task.description}</p>
                    {status?.error && (
                      <div className="flex items-center gap-1 text-xs text-red-600">
                        <AlertCircle className="h-3 w-3" />
                        <span className="truncate">{status.error}</span>
                      </div>
                    )}
                  </div>
                  <div className="flex gap-1 ml-3 flex-shrink-0">
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


