"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  BarChart,
  Bot,
  Brain,
  CheckCircle2,
  Clock,
  Database,
  Download,
  FileText,
  Layers,
  Loader2,
  Pause,
  Play,
  RefreshCw,
  Share2,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import EmptyState from "@/components/EmptyState";
import EventsDisplay from "@/components/TaskEvents/EventsDisplay";
import LiveEventIndicator from "@/components/TaskEvents/LiveEventIndicator";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import {
  cancelAgentTask,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
} from "@/lib/browser-api";

// Types for task data
interface TaskDetail {
  id: string;
  agent_id: string;
  description: string;
  status: string;
  result?: Record<string, unknown>;
  created_at: string;
  execution_id?: string | null;
  agent_name?: string;
  agent_description?: string;
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
  result?: Record<string, unknown>;
  message?: string;
  artifacts?: unknown[];
  session_id?: string;
  usage_metadata?: Record<string, unknown>;
}

export default function TaskDetailsPage() {
  const params = useParams();
  const router = useRouter();
  const id = Array.isArray(params.id) ? params.id[0] : (params.id as string);
  const [activeTab, setActiveTab] = useState("overview");

  // State for real data
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

  // Events hook for real-time events
  const {
    events,
    loading: eventsLoading,
    error: eventsError,
    connected: eventsConnected,
    refresh: refreshEvents,
  } = useTaskEvents(task?.agent_id || null, task?.id || null, {
    includeHistory: true,
    autoConnect: true,
    onEvent: (event) => {
      console.log("New event received:", event);
    },
    onError: (error) => {
      console.error("Events error:", error);
    },
  });

  const loadTaskData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Since we only have the task ID from the URL, we need to find the task
      // by searching through all agents' tasks. This is not ideal but necessary
      // given the current API structure.

      // First, get all tasks to find the one with matching ID
      const { getAllTasks } = await import("@/lib/browser-api");
      const { data: allTasks, error: tasksError } = await getAllTasks();

      if (tasksError || !allTasks) {
        throw new Error("Failed to load tasks");
      }

      // Find the task with matching ID
      const foundTask = allTasks.find((task) => task.id.toString() === id);

      if (!foundTask) {
        setError("Task not found");
        setTask(null);
        return;
      }

      // Set basic task data
      setTask({
        id: foundTask.id.toString(),
        agent_id: foundTask.agent_id.toString(),
        description: foundTask.description,
        status: foundTask.status,
        result: foundTask.result || undefined,
        created_at: foundTask.created_at,
        execution_id: foundTask.execution_id || undefined,
        agent_name: foundTask.agent_name,
        agent_description: foundTask.agent_description || undefined,
      });

      // Get detailed status information
      const statusResponse = await getAgentTaskStatus(
        foundTask.agent_id.toString(),
        foundTask.id.toString()
      );

      if (!statusResponse.error && statusResponse.data) {
        setTaskStatus(statusResponse.data as TaskStatus);
      }
    } catch (err) {
      console.error("Failed to load task data:", err);
      setError(
        "Failed to load task details. The task may not exist or you may not have permission to view it."
      );
    } finally {
      setLoading(false);
    }
  }, [id]);

  // Load task data on mount and when ID changes
  useEffect(() => {
    loadTaskData();
  }, [loadTaskData]);

  const handleRefresh = async () => {
    setRefreshing(true);
    await loadTaskData();
    await refreshEvents();
    setRefreshing(false);
  };

  // Task control handlers
  const handlePauseTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await pauseAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while pausing the task";
        toast.error("Failed to pause task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task paused successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to pause task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
    }
  };

  const handleResumeTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await resumeAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg || "An error occurred while resuming the task";
        toast.error("Failed to resume task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task resumed successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to resume task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
    }
  };

  const handleCancelTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error } = await cancelAgentTask(task.agent_id, task.id);

      if (error) {
        const errorMessage =
          error.detail?.[0]?.msg ||
          (error as any).message ||
          "An error occurred while cancelling the task";
        toast.error("Failed to cancel task", {
          description: errorMessage,
        });
      } else {
        toast.success("Task cancelled successfully");
        // Refresh task data to get updated status
        await loadTaskData();
      }
    } catch (err) {
      toast.error("Failed to cancel task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
      setShowCancelDialog(false);
    }
  };

  // Determine which control buttons to show based on task status
  const getControlButtons = () => {
    if (!isActive) return null;

    const buttons = [];

    if (currentStatus === "running") {
      buttons.push(
        <Button
          key="pause"
          variant="outline"
          className="gap-1"
          onClick={handlePauseTask}
          disabled={controlling}
        >
          <Pause className="h-4 w-4" />
          Pause
        </Button>
      );
    }

    if (currentStatus === "paused") {
      buttons.push(
        <Button
          key="resume"
          variant="outline"
          className="gap-1"
          onClick={handleResumeTask}
          disabled={controlling}
        >
          <Play className="h-4 w-4" />
          Resume
        </Button>
      );
    }

    if (["running", "paused"].includes(currentStatus)) {
      buttons.push(
        <Button
          key="cancel"
          variant="destructive"
          className="gap-1"
          onClick={() => setShowCancelDialog(true)}
          disabled={controlling}
        >
          <X className="h-4 w-4" />
          Cancel
        </Button>
      );
    }

    return buttons;
  };

  // Status badge color
  const getStatusColor = (status: string) => {
    if (status === "running" || status === "completed")
      return "bg-green-100 text-green-700";
    if (status === "paused") return "bg-yellow-100 text-yellow-700";
    return "bg-red-100 text-red-700";
  };

  // Log level color
  const getLogLevelColor = (level: string) => {
    if (level === "success") return "text-green-600";
    if (level === "error") return "text-red-600";
    if (level === "warning") return "text-yellow-600";
    return "text-blue-600";
  };

  // Show loading state
  if (loading) {
    return (
      <div className="p-8">
        <LoadingSpinner />
      </div>
    );
  }

  // Show error state inside ContentBlock
  if (error || !task) {
    return (
      <ContentBlock
        header={{
          breadcrumb: [
            { label: "Tasks", href: "/tasks" },
            {
              label: task?.agent_name || `Agent ${task?.agent_id || "Unknown"}`,
              href: task?.agent_id ? `/agents/${task.agent_id}/tasks` : undefined,
            },
            { label: task?.description || "Task Details" },
          ],
        }}
      >
        <EmptyState
          title="Task Not Found"
          description={"The requested task could not be found."}
          iconsType="tasks"
          action={{ label: "Back to Tasks", href: "/tasks" }}
          additionAction={{ label: "Try Again", onClick: handleRefresh }}
        />
      </ContentBlock>
    );
  }

  // Determine if task is active based on status
  const isActive = ["running", "paused"].includes(task.status);

  // Get current status from taskStatus or fallback to task.status
  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at;
  const endTime = taskStatus?.end_time;
  const errorMessage = taskStatus?.error;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Tasks", href: "/tasks" },
          {
            label: task?.agent_name || `Agent ${task?.agent_id || "Unknown"}`,
            href: task?.agent_id ? `/agents/${task.agent_id}/tasks` : undefined,
          },
          { label: task?.description || "Task Details" },
        ],
      }}
    >
      {/* Compact Header */}
      <div className="mb-4 rounded-lg border border-gray-200 bg-gradient-to-r from-white to-gray-50 p-4 shadow-sm dark:border-gray-700 dark:from-gray-900 dark:to-gray-800">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex items-start gap-4">
            {/* Smaller Status Indicator */}
            <div className="flex-shrink-0">
              <div
                className={`flex h-10 w-10 items-center justify-center rounded-lg ${
                  currentStatus === "running"
                    ? "bg-blue-50 dark:bg-blue-900/30"
                    : currentStatus === "completed" ||
                        currentStatus === "success"
                      ? "bg-green-50 dark:bg-green-900/30"
                      : currentStatus === "paused"
                        ? "bg-yellow-50 dark:bg-yellow-900/30"
                        : "bg-red-50 dark:bg-red-900/30"
                }`}
              >
                <div
                  className={`h-4 w-4 rounded-full ${
                    currentStatus === "running"
                      ? "animate-pulse bg-blue-500"
                      : currentStatus === "completed" ||
                          currentStatus === "success"
                        ? "bg-green-500"
                        : currentStatus === "paused"
                          ? "bg-yellow-500"
                          : "bg-red-500"
                  }`}
                />
              </div>
            </div>

            {/* Compact Main Content */}
            <div className="min-w-0 flex-1">
              <div className="mb-1 flex items-center gap-2">
                <h1 className="truncate text-xl font-bold text-gray-900 dark:text-gray-100">
                  {task.description}
                </h1>
                <Badge
                  className={`px-2 py-0.5 text-xs ${
                    currentStatus === "running"
                      ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                      : currentStatus === "completed" ||
                          currentStatus === "success"
                        ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                        : currentStatus === "paused"
                          ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"
                          : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                  }`}
                >
                  {currentStatus.charAt(0).toUpperCase() +
                    currentStatus.slice(1)}
                </Badge>
              </div>

              <p className="mb-2 text-sm text-gray-600 dark:text-gray-400">
                ID:{" "}
                <span className="rounded bg-gray-100 px-1 py-0.5 font-mono text-xs dark:bg-gray-800">
                  {task.id}
                </span>
              </p>

              {/* Compact Meta Information */}
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4">
                <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                  <Bot className="h-3 w-3 text-blue-600" />
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {task.agent_name || `Agent ${task.agent_id}`}
                  </span>
                </div>

                <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                  <Clock className="h-3 w-3 text-green-600" />
                  <span className="font-medium text-gray-900 dark:text-gray-100">
                    {isActive
                      ? `Started ${new Date(startTime).toLocaleDateString()}`
                      : endTime
                        ? `${executionTime}`
                        : `${new Date(task.created_at).toLocaleDateString()}`}
                  </span>
                </div>

                {task.execution_id && (
                  <div className="flex items-center gap-2 text-xs text-gray-600 dark:text-gray-400">
                    <Database className="h-3 w-3 text-purple-600" />
                    <span className="font-mono font-medium text-gray-900 dark:text-gray-100">
                      {task.execution_id.slice(-8)}
                    </span>
                  </div>
                )}

                {/* Live Event Indicator */}
                <div className="flex items-center gap-2 text-xs">
                  <LiveEventIndicator
                    connected={eventsConnected}
                    latestEvent={events[events.length - 1]}
                    eventCount={events.length}
                  />
                </div>
              </div>
            </div>
          </div>

          {/* Compact Action Buttons */}
          <div className="flex flex-wrap gap-1">
            {/* Task Control Buttons */}
            {getControlButtons()}

            <Button
              variant="outline"
              size="sm"
              className="gap-1"
              onClick={handleRefresh}
              disabled={refreshing}
            >
              <RefreshCw
                className={`h-3 w-3 ${refreshing ? "animate-spin" : ""}`}
              />
              Refresh
            </Button>
            <Button variant="outline" size="sm" className="gap-1">
              <Download className="h-3 w-3" />
              Export
            </Button>
            <Button variant="outline" size="sm" className="gap-1">
              <Share2 className="h-3 w-3" />
              Share
            </Button>
          </div>
        </div>
      </div>

      {/* Compact error message */}
      {errorMessage && (
        <Card className="mb-4 border-destructive">
          <CardContent className="pb-3 pt-3">
            <div className="flex items-center gap-2 text-destructive">
              <AlertTriangle className="h-4 w-4" />
              <span className="text-sm font-medium">Error</span>
            </div>
            <p className="mt-1 text-xs text-muted-foreground">{errorMessage}</p>
          </CardContent>
        </Card>
      )}

      {/* Compact Progress Section for Active Tasks */}
      {isActive && (
        <div className="mb-4 rounded-lg border border-blue-200 bg-gradient-to-r from-blue-50 to-indigo-50 p-3 dark:border-blue-800 dark:from-blue-900/20 dark:to-indigo-900/20">
          <div className="flex items-center gap-3">
            <div className="flex-shrink-0">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-blue-100 dark:bg-blue-900/40">
                <Loader2 className="h-4 w-4 animate-spin text-blue-600" />
              </div>
            </div>
            <div className="min-w-0 flex-1">
              <div className="mb-2 flex items-center justify-between">
                <h3 className="text-sm font-medium text-gray-900 dark:text-gray-100">
                  {currentStatus === "running"
                    ? "Running..."
                    : currentStatus === "paused"
                      ? "Paused"
                      : currentStatus}
                </h3>
                <span className="text-xs text-gray-600 dark:text-gray-400">
                  {taskStatus?.message || "In progress"}
                </span>
              </div>

              {/* Compact Progress Bar */}
              <div className="mb-2">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-white dark:bg-gray-800">
                  <div
                    className={`h-full rounded-full transition-all duration-300 ${
                      currentStatus === "running"
                        ? "animate-pulse bg-gradient-to-r from-blue-500 to-blue-600"
                        : currentStatus === "paused"
                          ? "bg-gradient-to-r from-yellow-400 to-yellow-500"
                          : "bg-gradient-to-r from-red-400 to-red-500"
                    }`}
                    style={{
                      width: currentStatus === "running" ? "65%" : "35%",
                    }}
                  />
                </div>
              </div>

              {/* Compact Artifacts Preview */}
              {taskStatus?.artifacts && taskStatus.artifacts.length > 0 && (
                <div className="flex flex-wrap gap-1">
                  <span className="mr-1 text-xs text-gray-700 dark:text-gray-300">
                    Generated:
                  </span>
                  {taskStatus.artifacts.slice(0, 2).map((artifact, index) => (
                    <div
                      key={index}
                      className="flex items-center gap-1 rounded bg-white px-2 py-0.5 text-xs dark:bg-gray-800"
                    >
                      <FileText className="h-2.5 w-2.5 text-blue-600" />
                      <span>
                        {typeof artifact === "string"
                          ? artifact
                          : `Artifact ${index + 1}`}
                      </span>
                    </div>
                  ))}
                  {taskStatus.artifacts.length > 2 && (
                    <span className="text-xs text-gray-500">
                      +{taskStatus.artifacts.length - 2} more
                    </span>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      <Tabs
        defaultValue="overview"
        value={activeTab}
        className="w-full"
        onValueChange={setActiveTab}
      >
        <TabsList className="mb-4">
          <TabsTrigger value="overview" className="text-xs">
            Overview
          </TabsTrigger>
          <TabsTrigger value="events" className="text-xs">
            Events
            {eventsConnected && (
              <div className="ml-1 h-1.5 w-1.5 animate-pulse rounded-full bg-green-500" />
            )}
          </TabsTrigger>
          <TabsTrigger value="logs" className="text-xs">
            Logs
          </TabsTrigger>
          <TabsTrigger value="artifacts" className="text-xs">
            Artifacts
          </TabsTrigger>
          <TabsTrigger value="memory" className="text-xs">
            Memory
          </TabsTrigger>
          <TabsTrigger value="metrics" className="text-xs">
            Metrics
          </TabsTrigger>
          {isActive && (
            <TabsTrigger value="configuration" className="text-xs">
              Config
            </TabsTrigger>
          )}
        </TabsList>
        <TabsContent value="overview">
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
            {/* Compact Task Details Card */}
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10">
                    <Layers className="h-4 w-4 text-primary" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Task Details</CardTitle>
                    <CardDescription className="text-xs">
                      Core information
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent className="space-y-3">
                {/* Compact Status */}
                <div className="flex items-center justify-between rounded-lg border bg-gray-50 p-2 dark:bg-gray-800">
                  <div className="flex items-center gap-2">
                    <div
                      className={`flex h-6 w-6 items-center justify-center rounded ${
                        currentStatus === "running"
                          ? "bg-blue-50 dark:bg-blue-900/30"
                          : currentStatus === "completed" ||
                              currentStatus === "success"
                            ? "bg-green-50 dark:bg-green-900/30"
                            : currentStatus === "paused"
                              ? "bg-yellow-50 dark:bg-yellow-900/30"
                              : "bg-red-50 dark:bg-red-900/30"
                      }`}
                    >
                      {currentStatus === "running" ? (
                        <Loader2 className="h-3 w-3 animate-spin text-blue-600" />
                      ) : currentStatus === "completed" ||
                        currentStatus === "success" ? (
                        <CheckCircle2 className="h-3 w-3 text-green-600" />
                      ) : currentStatus === "paused" ? (
                        <Pause className="h-3 w-3 text-yellow-600" />
                      ) : (
                        <XCircle className="h-3 w-3 text-red-600" />
                      )}
                    </div>
                    <div>
                      <p className="text-sm font-medium text-gray-900 dark:text-gray-100">
                        Status
                      </p>
                    </div>
                  </div>
                  <Badge
                    className={`px-2 py-0.5 text-xs ${
                      currentStatus === "running"
                        ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
                        : currentStatus === "completed" ||
                            currentStatus === "success"
                          ? "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300"
                          : currentStatus === "paused"
                            ? "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300"
                            : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                    }`}
                  >
                    {currentStatus.charAt(0).toUpperCase() +
                      currentStatus.slice(1)}
                  </Badge>
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
                        {task.agent_description || "No description available"}
                      </p>
                    </div>
                  </div>
                </div>

                {/* Compact Timing Information */}
                <div className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-gray-600 dark:text-gray-400">
                      Created
                    </span>
                    <span className="font-medium text-gray-900 dark:text-gray-100">
                      {new Date(task.created_at).toLocaleDateString()}
                    </span>
                  </div>
                  {startTime && startTime !== task.created_at && (
                    <div className="flex items-center justify-between text-xs">
                      <span className="text-gray-600 dark:text-gray-400">
                        Started
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
                          Completed
                        </span>
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {new Date(endTime).toLocaleDateString()}
                        </span>
                      </div>
                      <div className="flex items-center justify-between text-xs">
                        <span className="text-gray-600 dark:text-gray-400">
                          Duration
                        </span>
                        <span className="font-medium text-gray-900 dark:text-gray-100">
                          {executionTime}
                        </span>
                      </div>
                    </>
                  )}
                </div>

                {/* Compact Execution ID */}
                {task.execution_id && (
                  <div className="rounded bg-gray-50 p-2 dark:bg-gray-700">
                    <p className="mb-0.5 text-xs text-gray-600 dark:text-gray-400">
                      Execution ID
                    </p>
                    <code className="break-all font-mono text-xs text-gray-900 dark:text-gray-100">
                      {task.execution_id}
                    </code>
                  </div>
                )}
              </CardContent>
            </Card>

            {/* Compact Task Results Card */}
            <Card className="shadow-sm">
              <CardHeader className="pb-3">
                <div className="flex items-center gap-2">
                  <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-green-100 dark:bg-green-900/30">
                    <FileText className="h-4 w-4 text-green-600" />
                  </div>
                  <div>
                    <CardTitle className="text-base">Task Results</CardTitle>
                    <CardDescription className="text-xs">
                      Output data
                    </CardDescription>
                  </div>
                </div>
              </CardHeader>
              <CardContent>
                {task.result ? (
                  <div className="space-y-2">
                    <div className="rounded-lg border border-green-200 bg-green-50 p-3 dark:border-green-800 dark:bg-green-900/20">
                      <div className="mb-2 flex items-center gap-2">
                        <CheckCircle2 className="h-4 w-4 text-green-600" />
                        <h4 className="text-sm font-medium text-green-900 dark:text-green-100">
                          Result
                        </h4>
                      </div>
                      <div className="max-h-32 overflow-y-auto rounded bg-white p-2 dark:bg-gray-800">
                        <pre className="whitespace-pre-wrap text-xs text-gray-900 dark:text-gray-100">
                          {JSON.stringify(task.result, null, 2)}
                        </pre>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="py-6 text-center">
                    <div className="mx-auto mb-2 flex h-12 w-12 items-center justify-center rounded-full bg-gray-100 dark:bg-gray-800">
                      {isActive ? (
                        <Loader2 className="h-6 w-6 animate-spin text-blue-500" />
                      ) : (
                        <FileText className="h-6 w-6 text-gray-400" />
                      )}
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-gray-900 dark:text-gray-100">
                      {isActive ? "Task Running" : "No Results"}
                    </h3>
                    <p className="text-xs text-gray-600 dark:text-gray-400">
                      {isActive
                        ? "Results will appear when complete"
                        : "No results produced"}
                    </p>
                  </div>
                )}

                {/* Compact Session Information */}
                {taskStatus?.session_id && (
                  <div className="mt-3 rounded border border-purple-200 bg-purple-50 p-2 dark:border-purple-800 dark:bg-purple-900/20">
                    <p className="mb-0.5 text-xs text-purple-600 dark:text-purple-400">
                      Session ID
                    </p>
                    <code className="break-all font-mono text-xs text-purple-900 dark:text-purple-100">
                      {taskStatus.session_id}
                    </code>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>
        <TabsContent value="events">
          <EventsDisplay
            events={events}
            loading={eventsLoading}
            error={eventsError}
            connected={eventsConnected}
            onRefresh={refreshEvents}
            showFilters={true}
            showStats={true}
            maxHeight="500px"
          />
        </TabsContent>
        <TabsContent value="logs">
          <Card>
            <CardHeader>
              <CardTitle>Execution Logs</CardTitle>
              <CardDescription>
                Detailed logs of the task execution
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="h-[400px] overflow-y-auto rounded-lg bg-muted p-4 font-mono text-sm">
                {/* Basic log entries based on task status */}
                <div className="mb-2">
                  <span className="text-muted-foreground">
                    [{new Date(task.created_at).toLocaleString()}]
                  </span>{" "}
                  <span className="text-blue-600">INFO:</span> Task created:{" "}
                  {task.description}
                </div>
                {taskStatus?.start_time && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">
                      [{new Date(taskStatus.start_time).toLocaleString()}]
                    </span>{" "}
                    <span className="text-blue-600">INFO:</span> Task execution
                    started
                  </div>
                )}
                {taskStatus?.message && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">
                      [{new Date().toLocaleString()}]
                    </span>{" "}
                    <span className="text-blue-600">INFO:</span>{" "}
                    {taskStatus.message}
                  </div>
                )}
                {taskStatus?.error && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">
                      [{new Date().toLocaleString()}]
                    </span>{" "}
                    <span className="text-red-600">ERROR:</span>{" "}
                    {taskStatus.error}
                  </div>
                )}
                {taskStatus?.end_time && (
                  <div className="mb-2">
                    <span className="text-muted-foreground">
                      [{new Date(taskStatus.end_time).toLocaleString()}]
                    </span>{" "}
                    <span
                      className={getLogLevelColor(
                        currentStatus === "completed" ? "success" : "error"
                      )}
                    >
                      {currentStatus === "completed" ? "SUCCESS" : "ERROR"}:
                    </span>{" "}
                    Task{" "}
                    {currentStatus === "completed"
                      ? "completed successfully"
                      : "execution ended"}
                  </div>
                )}
                {isActive && currentStatus === "running" && (
                  <div className="animate-pulse">
                    <span className="text-muted-foreground">
                      [{new Date().toLocaleString()}]
                    </span>{" "}
                    <span className="text-blue-600">INFO:</span> Task is
                    currently running...
                  </div>
                )}
                {!isActive && !taskStatus?.end_time && (
                  <div className="py-8 text-center text-muted-foreground">
                    <FileText className="mx-auto mb-2 h-8 w-8 opacity-50" />
                    <p>No detailed execution logs available</p>
                    <p className="mt-1 text-xs">
                      Logs will be available in future versions
                    </p>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="metrics">
          <Card>
            <CardHeader>
              <CardTitle>Performance Metrics</CardTitle>
              <CardDescription>
                Key metrics for this task execution
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
                <div className="rounded-lg bg-muted p-4">
                  <div className="mb-1 text-sm text-muted-foreground">
                    Execution Time
                  </div>
                  <div className="text-2xl font-bold">{executionTime}</div>
                </div>
                <div className="rounded-lg bg-muted p-4">
                  <div className="mb-1 text-sm text-muted-foreground">
                    Status
                  </div>
                  <div className="text-2xl font-bold">{currentStatus}</div>
                </div>
                <div className="rounded-lg bg-muted p-4">
                  <div className="mb-1 text-sm text-muted-foreground">
                    Execution ID
                  </div>
                  <div className="truncate text-lg font-bold">
                    {task.execution_id || "N/A"}
                  </div>
                </div>
                <div className="rounded-lg bg-muted p-4">
                  <div className="mb-1 text-sm text-muted-foreground">
                    Usage Data
                  </div>
                  <div className="text-2xl font-bold">
                    {taskStatus?.usage_metadata ? "Available" : "N/A"}
                  </div>
                </div>
              </div>
              {taskStatus?.usage_metadata && (
                <div className="mt-6">
                  <h4 className="mb-2 text-sm font-medium">Usage Metadata</h4>
                  <div className="max-h-40 overflow-y-auto rounded-lg bg-muted p-3 font-mono text-sm">
                    <pre>
                      {JSON.stringify(taskStatus.usage_metadata, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
              <div className="mt-8 flex justify-center">
                <div className="text-center text-muted-foreground">
                  <BarChart className="mx-auto mb-4 h-32 w-32 opacity-50" />
                  <p>
                    Detailed performance charts will be available in future
                    versions
                  </p>
                  <p className="mt-1 text-xs">
                    Metrics are collected from Temporal workflow execution
                  </p>
                </div>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="artifacts">
          <Card>
            <CardHeader>
              <CardTitle>Artifacts</CardTitle>
              <CardDescription>
                Files and outputs generated by this task
              </CardDescription>
            </CardHeader>
            <CardContent>
              {taskStatus?.artifacts && taskStatus.artifacts.length > 0 ? (
                <div className="space-y-4">
                  {taskStatus.artifacts.map((artifact, index) => (
                    <div
                      key={index}
                      className="flex items-center justify-between rounded-lg border p-4"
                    >
                      <div className="flex items-center gap-3">
                        <FileText className="h-8 w-8 text-primary" />
                        <div>
                          <p className="font-medium">
                            {typeof artifact === "string"
                              ? artifact
                              : `Artifact ${index + 1}`}
                          </p>
                          <p className="text-sm text-muted-foreground">
                            Generated by task execution
                          </p>
                        </div>
                      </div>
                      <Button
                        variant="outline"
                        size="sm"
                        className="gap-1"
                        disabled
                      >
                        <Download className="h-4 w-4" />
                        Download
                      </Button>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="py-12 text-center">
                  <FileText className="mx-auto mb-4 h-16 w-16 text-muted-foreground opacity-50" />
                  <h3 className="mb-2 text-lg font-semibold">No Artifacts</h3>
                  <p className="text-muted-foreground">
                    {isActive
                      ? "Artifacts will appear here as the task generates outputs."
                      : "This task did not generate any artifacts."}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </TabsContent>
        <TabsContent value="memory">
          <Card>
            <CardHeader>
              <CardTitle>Memory Context</CardTitle>
              <CardDescription>
                Current memory state and context information
              </CardDescription>
            </CardHeader>
            <CardContent>
              <div className="py-12 text-center">
                <Brain className="mx-auto mb-4 h-16 w-16 text-muted-foreground opacity-50" />
                <h3 className="mb-2 text-lg font-semibold">Memory Context</h3>
                <p className="mb-4 text-muted-foreground">
                  Memory context information is not yet available through the
                  current API.
                </p>
                <p className="text-xs text-muted-foreground">
                  This feature will be implemented in future versions to show
                  task memory state and context.
                </p>
              </div>
            </CardContent>
          </Card>
        </TabsContent>
        {isActive && (
          <TabsContent value="configuration">
            <Card>
              <CardHeader>
                <CardTitle>Task Configuration</CardTitle>
                <CardDescription>
                  Settings and parameters for this task execution
                </CardDescription>
              </CardHeader>
              <CardContent>
                <div className="py-12 text-center">
                  <Database className="mx-auto mb-4 h-16 w-16 text-muted-foreground opacity-50" />
                  <h3 className="mb-2 text-lg font-semibold">
                    Task Configuration
                  </h3>
                  <p className="mb-4 text-muted-foreground">
                    Task configuration details are not yet available through the
                    current API.
                  </p>
                  <p className="text-xs text-muted-foreground">
                    Configuration settings will be displayed here in future
                    versions.
                  </p>
                </div>
              </CardContent>
            </Card>
          </TabsContent>
        )}
      </Tabs>

      {/* Cancel Confirmation Dialog */}
      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cancel Task</DialogTitle>
            <DialogDescription>
              Are you sure you want to cancel this task? This action cannot be
              undone and will terminate the task execution immediately.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setShowCancelDialog(false)}
              disabled={controlling}
            >
              Keep Running
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelTask}
              disabled={controlling}
            >
              {controlling ? (
                <>
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <X className="mr-2 h-4 w-4" />
                  Cancel Task
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
