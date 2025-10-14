"use client";

import React, { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { 
  Bot, 
  CheckCircle,
  Pause,
  Play,
  Square,
  ArrowLeft,
  Clock
} from "lucide-react";
import Link from "next/link";
import {
  getTaskStatus,
  pauseTask,
  resumeTask,
  cancelTask,
  getTaskMessages
} from "./actions";
import AgentChat from "@/components/Chat/AgentChat";

interface Agent {
  id: string;
  name: string;
  description?: string | null;
  status: string;
}

interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  updated_at?: string;
  agent_id: string;
}

interface TaskStatus {
  status: string;
  task_id: string;
  agent_id: string;
  start_time?: string;
  end_time?: string;
  execution_time?: string;
  message?: string;
  error?: string;
}

interface Props {
  agent: Agent;
  taskId: string;
  task?: Task;
}

export default function AgentTaskClient({ agent, taskId, task }: Props) {
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [messages, setMessages] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    loadTaskData();
  }, [agent.id, taskId]);

  const loadTaskData = async () => {
    setLoading(true);
    try {
      // Load task status
      const statusResponse = await getTaskStatus(agent.id, taskId);
      if (statusResponse.data) {
        setTaskStatus(statusResponse.data as TaskStatus);
      }

      // Load task messages if available
      try {
        const messagesResponse = await getTaskMessages(agent.id, taskId);
        if (messagesResponse.data) {
          setMessages(messagesResponse.data);
        }
      } catch (error) {
        // Messages endpoint might not exist yet, that's okay
      }
    } catch (error) {
      // Failed to load task data
    } finally {
      setLoading(false);
    }
  };

  const handleTaskAction = async (action: "pause" | "resume" | "cancel") => {
    try {
      let result;
      switch (action) {
        case "pause":
          result = await pauseTask(agent.id, taskId);
          break;
        case "resume":
          result = await resumeTask(agent.id, taskId);
          break;
        case "cancel":
          result = await cancelTask(agent.id, taskId);
          break;
      }

      if (!result.error) {
        loadTaskData(); // Refresh data
      }
    } catch (error) {
      console.error(`Failed to ${action} task:`, error);
    }
  };

  const getStatusBadge = () => {
    const status = task?.status || taskStatus?.status;
    const statusColors = {
      "completed": "bg-green-50 text-green-700 border-green-200 dark:bg-green-950/30 dark:text-green-300 dark:border-green-800",
      "running": "bg-blue-50 text-blue-700 border-blue-200 dark:bg-blue-950/30 dark:text-blue-300 dark:border-blue-800",
      "failed": "bg-red-50 text-red-700 border-red-200 dark:bg-red-950/30 dark:text-red-300 dark:border-red-800",
      "paused": "bg-yellow-50 text-yellow-700 border-yellow-200 dark:bg-yellow-950/30 dark:text-yellow-300 dark:border-yellow-800"
    };

    return (
      <Badge 
        variant="outline" 
        className={statusColors[status as keyof typeof statusColors] || "bg-gray-50 text-gray-700 border-gray-200"}
      >
        {status}
      </Badge>
    );
  };

  const isActiveTask = ["running", "paused"].includes(task?.status || taskStatus?.status || "");

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 border-2 border-gray-400 border-t-transparent rounded-full animate-spin" />
          <span className="text-sm text-gray-500">Loading task...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Task Header */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg p-6">
        <div className="flex items-start justify-between mb-4">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-full bg-gradient-to-br from-gray-800 to-gray-900 flex items-center justify-center shadow-sm">
              <Bot className="h-5 w-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-semibold text-gray-900 dark:text-gray-100">
                {agent.name}
              </h1>
              <p className="text-sm text-gray-500 dark:text-gray-400">
                Task ID: {taskId}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            {getStatusBadge()}
            {isActiveTask && (
              <div className="flex gap-1">
                {task?.status === "running" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleTaskAction("pause")}
                  >
                    <Pause className="h-4 w-4 mr-2" />
                    Pause
                  </Button>
                )}
                {task?.status === "paused" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleTaskAction("resume")}
                  >
                    <Play className="h-4 w-4 mr-2" />
                    Resume
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => handleTaskAction("cancel")}
                >
                  <Square className="h-4 w-4 mr-2" />
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </div>

        {/* Task Details */}
        {task && (
          <div className="space-y-2">
            <div>
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">Description:</span>
              <p className="text-sm text-gray-600 dark:text-gray-300 mt-1">{task.description}</p>
            </div>
            <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-400">
              <div className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                <span>Created {new Date(task.created_at).toLocaleString()}</span>
              </div>
              {taskStatus?.start_time && (
                <div className="flex items-center gap-1">
                  <span>Started {new Date(taskStatus.start_time).toLocaleString()}</span>
                </div>
              )}
              {taskStatus?.end_time && (
                <div className="flex items-center gap-1">
                  <span>Ended {new Date(taskStatus.end_time).toLocaleString()}</span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error Display */}
        {taskStatus?.error && (
          <div className="mt-4 p-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800 rounded-lg">
            <p className="text-sm text-red-700 dark:text-red-300">{taskStatus.error}</p>
          </div>
        )}
      </div>

      {/* Chat Interface */}
      <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-lg overflow-hidden">
        <AgentChat
          agent={agent}
          taskId={taskId}
          initialMessages={messages}
          className="w-full border-0"
          height="600px"
        />
      </div>
    </div>
  );
}