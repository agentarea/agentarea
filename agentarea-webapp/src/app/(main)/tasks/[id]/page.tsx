"use client";

import { useCallback, useEffect, useState } from "react";
import { useParams } from "next/navigation";
import {
  Info,
  Loader2,
  Pause,
  Play,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import EmptyState from "@/components/EmptyState";
import TaskInfoPanel from "./components/TaskInfoPanel";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useTaskEvents } from "@/hooks/useTaskEvents";
import {
  cancelAgentTask,
  getAgentTaskStatus,
  pauseAgentTask,
  resumeAgentTask,
} from "@/lib/browser-api";
import FullChat from "@/components/Chat/FullChat";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import { useIsMobile } from "@/hooks/use-mobile";

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
  const id = Array.isArray(params.id) ? params.id[0] : (params.id as string);
  const isMobile = useIsMobile();

  // State for real data
  const [task, setTask] = useState<TaskDetail | null>(null);
  const [taskStatus, setTaskStatus] = useState<TaskStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [isTaskInfoSheetOpen, setIsTaskInfoSheetOpen] = useState(false);

  // Events hook for real-time events
  const { refresh: refreshEvents } = useTaskEvents(
    task?.agent_id || null,
    task?.id || null,
    {
      includeHistory: true,
      autoConnect: true,
    }
  );

  const loadTaskData = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Get all tasks to find the one with matching ID
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

  // Show loading state
  if (loading) {
    return (
      <div className="p-8">
        <LoadingSpinner />
      </div>
    );
  }

  // Show error state
  if (error || !task) {
    return (
      <EmptyState
        title="Task Not Found"
        description={"The requested task could not be found."}
        iconsType="tasks"
        action={{ label: "Back to Tasks", href: "/tasks" }}
        additionAction={{ label: "Try Again", onClick: handleRefresh }}
      />
    );
  }

  // Determine if task is active based on status
  const isActive = ["running", "paused"].includes(task.status);

  // Get current status from taskStatus or fallback to task.status
  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at;
  const endTime = taskStatus?.end_time;

  return (
    <>
      <ResizablePanelGroup direction="horizontal" className="h-full w-full">
        {/* Left Panel - Chat */}
        <ResizablePanel defaultSize={isMobile ? 100 : 60} minSize={isMobile ? 100 : 30}>
          <div className="relative h-full py-5 px-3 flex-1 overflow-auto">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 h-full">
              {/* Mobile button to open task info */}
              {isMobile && (
                <div className="absolute top-4 right-4 z-10">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setIsTaskInfoSheetOpen(true)}
                    className="gap-2"
                  >
                    <Info className="h-4 w-4" />
                    Task Info
                  </Button>
                </div>
              )}
              <FullChat
                agent={{
                  id: task.agent_id,
                  name: task.agent_name || `Agent ${task.agent_id}`,
                  description: task.agent_description || undefined,
                }}
                taskId={task.id}
                placeholder={`Chat with ${task.agent_name || `Agent ${task.agent_id}`}`}
              />
            </div>
          </div>
        </ResizablePanel>

        {/* Right Panel - Task Information */}
        {!isMobile && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={40} minSize={20}>
              <div className="h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700 px-4">
                <TaskInfoPanel
                  task={task}
                  currentStatus={currentStatus}
                  isActive={isActive}
                  startTime={startTime}
                  endTime={endTime}
                  executionTime={executionTime}
                />
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>

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
            <DialogClose asChild>
              <Button variant="outline" disabled={controlling}>
                Keep Running
              </Button>
            </DialogClose>
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

      {/* Mobile Task Info Sheet */}
      <Sheet open={isTaskInfoSheetOpen} onOpenChange={setIsTaskInfoSheetOpen}>
        <SheetContent side="right" className="w-full sm:max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>Task Information</SheetTitle>
          </SheetHeader>
          <TaskInfoPanel
            task={task}
            currentStatus={currentStatus}
            isActive={isActive}
            startTime={startTime}
            endTime={endTime}
            executionTime={executionTime}
          />
        </SheetContent>
      </Sheet>
    </>
  );
}
