"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Bot, Loader2, X } from "lucide-react";
import { toast } from "sonner";
import { ChatWelcome } from "@/components/Chat/componets/ChatWelcome";
import FullChat from "@/components/Chat/FullChat";
import EmptyState from "@/components/EmptyState";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
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
import { useTaskEvents } from "@/hooks/useTaskEvents";
import {
  cancelAgentTaskAction as cancelAgentTask,
  pauseAgentTaskAction as pauseAgentTask,
  resumeAgentTaskAction as resumeAgentTask,
} from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const { task, taskStatus, loading, error, refresh } = useTaskContext();
  const t = useTranslations("TaskDetailPage");

  const [refreshing, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);

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
        const errorMessage = error.detail?.[0]?.msg || t("errorWhilePausing");
        toast.error(t("failedToPause"), {
          description: errorMessage,
        });
      } else {
        toast.success(t("pausedSuccessfully"));
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error(t("failedToPause"), {
        description: t("unexpectedError"),
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
        const errorMessage = error.detail?.[0]?.msg || t("errorWhileResuming");
        toast.error(t("failedToResume"), {
          description: errorMessage,
        });
      } else {
        toast.success(t("resumedSuccessfully"));
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error(t("failedToResume"), {
        description: t("unexpectedError"),
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
          t("errorWhileCancelling");
        toast.error(t("failedToCancel"), {
          description: errorMessage,
        });
      } else {
        toast.success(t("cancelledSuccessfully"));
        // Refresh task data to get updated status
        await refresh();
      }
    } catch (err) {
      toast.error(t("failedToCancel"), {
        description: t("unexpectedError"),
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
        title={t("taskNotFound")}
        description={t("taskNotFoundDescription")}
        iconsType="tasks"
        action={{ label: t("backToTasks"), href: "/tasks" }}
        additionAction={{ label: t("tryAgain"), onClick: handleRefresh }}
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

  const welcomeComponent = (
    <ChatWelcome
      icon={Bot}
      variant="neutral"
      size="sm"
      animate={false}
      titleClassName="text-muted-foreground opacity-70"
      title={t("chatWith", { agentName: task.agent_name || "Agent" })}
    />
  );

  return (
    <>
      <div className="flex h-full w-full">
        {/* Left side - Chat (flexible) */}
        <div className="flex-1">
          <div className="relative h-full py-5 px-3 flex-1 overflow-auto">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 h-full">
              <FullChat
                welcomeComponent={welcomeComponent}
                agent={{
                  id: task.agent_id,
                  name: task.agent_name || `Agent ${task.agent_id}`,
                  description: task.agent_description || undefined,
                }}
                taskId={task.id}
                placeholder={t("chatWith", {
                  agentName: task.agent_name || `Agent ${task.agent_id}`,
                })}
              />
            </div>
          </div>
        </div>

        <TaskInfoPanelDock
          storageKey="task-info-panel"
          panel={
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
          }
        />
      </div>

      <Dialog open={showCancelDialog} onOpenChange={setShowCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("cancelTask")}</DialogTitle>
            <DialogDescription>{t("cancelTaskDescription")}</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose asChild>
              <Button variant="outline" disabled={controlling}>
                {t("keepRunning")}
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
                  {t("cancelling")}
                </>
              ) : (
                <>
                  <X className="mr-2 h-4 w-4" />
                  {t("cancelTask")}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
