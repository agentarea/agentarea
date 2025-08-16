"use client";

import React, { useState, useEffect } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { 
  Bot, 
  CheckCircle,
  Pause,
  Play,
  Square,
  FileText,
  AlertCircle,
  Plus
} from "lucide-react";
import Link from "next/link";
import { 
  listAgentTasks,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
  cancelAgentTask
} from "@/lib/api";
import { AgentChat } from "@/components/Chat";

interface Agent {
  id: string;
  name: string;
  description?: string;
  status: string;
  created_at?: string;
  updated_at?: string;
}


interface Task {
  id: string;
  description: string;
  status: string;
  created_at: string;
  updated_at?: string;
  agent_id: string;
  agent_name?: string;
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
  artifacts?: Array<{
    name: string;
    type: string;
    content?: string;
  }>;
  usage_metadata?: any;
  session_id?: string;
}

interface Props {
  agent: Agent;
}



export default function AgentDetailClient({ agent }: Props) {
  const [activeTab, setActiveTab] = useState("create");
  const [tasks, setTasks] = useState<Task[]>([]);
  const [tasksLoading, setTasksLoading] = useState(false);
  const [taskStatuses, setTaskStatuses] = useState<Record<string, TaskStatus>>({});

  // Load tasks only when tasks tab is activated
  useEffect(() => {
    if (activeTab === "tasks") {
      loadTasks();
    }
  }, [activeTab, agent.id]);

  const loadTasks = async () => {
    setTasksLoading(true);
    try {
      const { data: tasksData, error } = await listAgentTasks(agent.id);
      if (!error && tasksData) {
        setTasks(tasksData);
        // Load status for each task
        for (const task of tasksData) {
          loadTaskStatus(task.id);
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
      const { data: statusData, error } = await getAgentTaskStatus(agent.id, taskId);
      if (!error && statusData) {
        setTaskStatuses(prev => ({
          ...prev,
          [taskId]: statusData as TaskStatus
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
          result = await pauseAgentTask(agent.id, taskId);
          break;
        case "resume":
          result = await resumeAgentTask(agent.id, taskId);
          break;
        case "cancel":
          result = await cancelAgentTask(agent.id, taskId);
          break;
      }
      
      if (!result.error) {
        // Refresh task status
        loadTaskStatus(taskId);
        // Refresh task list
        loadTasks();
      }
    } catch (error) {
      console.error(`Failed to ${action} task:`, error);
    }
  };

  // Handle task creation from chat with URL update (no redirect)
  const handleTaskCreated = (taskId: string) => {
    // Update URL without redirecting to avoid loading states
    const newUrl = `/agents/${agent.id}/tasks/${taskId}`;
    window.history.pushState({}, '', newUrl);
    console.log('URL updated to:', newUrl);
  };

  return (
    <div className="space-y-4">
      {/* Compact Header */}
      <div className="flex items-center gap-3">
        <div className="h-8 w-8 bg-gray-100 rounded flex items-center justify-center">
          <Bot className="h-4 w-4 text-gray-600" />
        </div>
        <div className="flex-1">
          <h1 className="text-lg font-medium text-gray-900">{agent.name}</h1>
        </div>
        <Badge 
          variant="secondary"
          className="bg-green-50 text-green-700 border-green-200 text-xs"
        >
          {agent.status}
        </Badge>
      </div>

      {/* Compact Navigation */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList className="h-auto p-0 bg-transparent border-b border-gray-100 rounded-none w-full justify-start">
          <TabsTrigger 
            value="create" 
            className="gap-2 px-3 py-2 rounded-none border-b-2 border-transparent data-[state=active]:border-gray-900 data-[state=active]:bg-transparent bg-transparent hover:bg-gray-50 transition-all duration-200 text-sm"
          >
            <Plus className="h-3 w-3" />
            Create Task
          </TabsTrigger>
          <TabsTrigger 
            value="tasks" 
            className="gap-2 px-3 py-2 rounded-none border-b-2 border-transparent data-[state=active]:border-gray-900 data-[state=active]:bg-transparent bg-transparent hover:bg-gray-50 transition-all duration-200 text-sm"
          >
            <CheckCircle className="h-3 w-3" />
            Current Tasks
          </TabsTrigger>
        </TabsList>

        <TabsContent value="create" className="py-4">
          <div className="bg-white border border-gray-200 rounded-lg">
            <AgentChat
              agent={agent}
              onTaskCreated={handleTaskCreated}
              className="w-full"
              height="500px"
            />
          </div>
        </TabsContent>

        <TabsContent value="tasks" className="py-4">
          <div className="space-y-2">
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
                  This agent hasn't been assigned any tasks yet.
                </p>
                <Button 
                  onClick={() => setActiveTab("create")}
                  size="sm"
                  className="gap-2"
                >
                  <Plus className="h-3 w-3" />
                  Create your first task
                </Button>
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
                                task.status === "completed" ? "bg-green-50 text-green-700 border-green-200" :
                                task.status === "running" ? "bg-blue-50 text-blue-700 border-blue-200" :
                                task.status === "failed" ? "bg-red-50 text-red-700 border-red-200" :
                                "bg-gray-50 text-gray-700 border-gray-200"
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
        </TabsContent>
      </Tabs>
    </div>
  );
} 