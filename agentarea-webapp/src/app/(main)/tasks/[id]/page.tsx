"use client";

import { useState } from "react";
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
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
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
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const isMobile = useIsMobile();
  const { task, taskStatus, loading, error, refresh } = useTaskContext();

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

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
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
        await refresh();
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
        await refresh();
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
        await refresh();
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

  // Show loading state
  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
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
  const startTime = taskStatus?.start_time || task.created_at || "";
  const endTime = taskStatus?.end_time;

  return (
    <>
      <div className="flex h-full w-full">
        {/* Left side - Chat (flexible) */}
        <div className="flex-1">
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
        </div>

        {/* Right side - fixed width task info (desktop only) */}
        {!isMobile && (
          <div className="relative h-full w-[360px]">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            {/* <div className="relative z-10 h-full overflow-auto pr-4"> */}
            <div className="relative z-10 h-full overflow-auto">
              <TaskInfoPanel
                task={{
                  id: task.id,
                  description: task.description || "",
                  agent_id: task.agent_id,
                  agent_name: task.agent_name,
                  agent_description: task.agent_description,
                  created_at: task.created_at || "",
                  execution_id: task.execution_id || null,
                  result: task.result,
                }}
                currentStatus={currentStatus}
                isActive={isActive}
                startTime={startTime}
                endTime={endTime}
                executionTime={executionTime}
              />
            </div>
          </div>
        )}
      </div>

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
            task={{
              id: task.id,
              description: task.description || "",
              agent_id: task.agent_id,
              agent_name: task.agent_name,
              agent_description: task.agent_description,
              created_at: task.created_at || "",
              execution_id: task.execution_id || null,
              result: task.result,
            }}
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
