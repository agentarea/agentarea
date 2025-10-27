"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { AlertCircle, CheckCircle, Pause, Play, Square } from "lucide-react";
import { Button } from "@/components/ui/button";
import { TaskItem, type TaskItemData } from "@/components/TaskItem";
import {
  getAgentTaskStatus,
  listAgentTasks,
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


  return (
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
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
        <div className="grid grid-cols-1 gap-2 md:grid-cols-2 lg:grid-cols-3">
          {tasks.map((task) => {
            const status = taskStatuses[task.id];

            return (
              <div key={task.id} className="space-y-1">
                <TaskItem task={task as unknown as TaskItemData} showAgentName={false} />
                <div className="flex items-center justify-between px-1">
                  {status?.error && (
                    <div className="flex items-center gap-1 text-xs text-red-600">
                      <AlertCircle className="h-3 w-3" />
                      <span className="truncate">{status.error}</span>
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
