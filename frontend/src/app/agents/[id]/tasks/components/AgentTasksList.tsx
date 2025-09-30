"use client";

import React, { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Link from "next/link";
// API вызовы теперь только на сервере
import { AlertCircle, CheckCircle, FileText, Pause, Play, Square } from "lucide-react";

interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  agent_id: string;
}

interface TaskStatus {
  task_id: string;
  agent_id: string;
  execution_id: string;
  status: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  error?: string;
  result?: any;
  message?: string;
  artifacts?: any;
  session_id?: string;
  usage_metadata?: any;
}

interface TaskWithStatus extends Task {
  taskStatus?: TaskStatus;
}

interface AgentTasksListProps {
  agentId: string;
  initialTasks: TaskWithStatus[];
  onPauseTask: (taskId: string) => Promise<any>;
  onResumeTask: (taskId: string) => Promise<any>;
  onCancelTask: (taskId: string) => Promise<any>;
}

export default function AgentTasksList({ 
  agentId, 
  initialTasks, 
  onPauseTask, 
  onResumeTask, 
  onCancelTask 
}: AgentTasksListProps) {
  const [tasks, setTasks] = useState<TaskWithStatus[]>(initialTasks);

  // Обновляем задачи только при изменении initialTasks
  useEffect(() => {
    setTasks(initialTasks);
  }, [initialTasks]);

  const handleTaskPause = async (taskId: string) => {
    try {
      const result = await onPauseTask(taskId);
      if (result.error) {
        console.error("Failed to pause task:", result.error);
      }
    } catch (error) {
      console.error("Failed to pause task:", error);
    }
  };

  const handleTaskResume = async (taskId: string) => {
    try {
      const result = await onResumeTask(taskId);
      if (result.error) {
        console.error("Failed to resume task:", result.error);
      }
    } catch (error) {
      console.error("Failed to resume task:", error);
    }
  };

  const handleTaskCancel = async (taskId: string) => {
    try {
      const result = await onCancelTask(taskId);
      if (result.error) {
        console.error("Failed to cancel task:", result.error);
      }
    } catch (error) {
      console.error("Failed to cancel task:", error);
    }
  };

  return (
    <div className="space-y-2 h-full overflow-auto">
      {tasks.length === 0 ? (
        <div className="text-center py-8 bg-white border border-gray-200 rounded-lg">
          <div className="h-8 w-8 bg-gray-100 rounded flex items-center justify-center mx-auto mb-3">
            <CheckCircle className="h-4 w-4 text-gray-400" />
          </div>
          <h3 className="font-medium text-gray-900 mb-1">No tasks yet</h3>
          <p className="text-sm text-gray-500 mb-4">
            This agent hasn't been assigned any tasks yet.
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
            const status = task.taskStatus;
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
                        onClick={() => handleTaskPause(task.id)}
                        className="h-7 px-2"
                      >
                        <Pause className="h-3 w-3" />
                      </Button>
                    )}
                    {task.status === "paused" && (
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={() => handleTaskResume(task.id)}
                        className="h-7 px-2"
                      >
                        <Play className="h-3 w-3" />
                      </Button>
                    )}
                    {isActive && (
                      <Button
                        size="sm"
                        variant="destructive"
                        onClick={() => handleTaskCancel(task.id)}
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


