"use client";

import { useCallback, useState } from "react";
import { Loader2, X } from "lucide-react";
import { toast } from "sonner";
import {
  TaskConversation,
  type TaskConversationActivity,
} from "@/components/Chat/TaskConversation";
import EmptyState from "@/components/EmptyState";
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
import { Skeleton } from "@/components/ui/skeleton";
import { cancelAgentTaskAction as cancelAgentTask } from "@/lib/server-actions";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const { task, taskStatus, policy, loading, error, refresh } =
    useTaskContext();
  const [, setRefreshing] = useState(false);
  const [controlling, setControlling] = useState(false);
  const [showCancelDialog, setShowCancelDialog] = useState(false);
  const [conversationActivity, setConversationActivity] =
    useState<TaskConversationActivity | null>(null);

  const handleActivityChange = useCallback(
    (activity: TaskConversationActivity) => setConversationActivity(activity),
    []
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  };

  const handleCancelTask = async () => {
    if (!task) return;

    try {
      setControlling(true);
      const { error: cancelError } = await cancelAgentTask(
        task.agent_id,
        task.id
      );

      if (cancelError) {
        const errorMessage =
          cancelError.detail?.[0]?.msg ||
          (cancelError as { message?: string }).message ||
          "An error occurred while cancelling the task";
        toast.error("Failed to cancel task", { description: errorMessage });
      } else {
        toast.success("Task cancelled successfully");
        await refresh();
      }
    } catch {
      toast.error("Failed to cancel task", {
        description: "An unexpected error occurred",
      });
    } finally {
      setControlling(false);
      setShowCancelDialog(false);
    }
  };

  if (loading) {
    return (
      <div className="mx-auto w-full max-w-3xl space-y-4 p-4" aria-hidden="true">
        {Array.from({ length: 5 }).map((_, index) => (
          <div
            key={index}
            className={`flex ${index % 2 ? "justify-end" : "justify-start"}`}
          >
            <Skeleton
              className={`h-16 rounded-lg ${index % 2 ? "w-1/2" : "w-2/3"}`}
            />
          </div>
        ))}
      </div>
    );
  }

  if (error || !task) {
    return (
      <EmptyState
        title={error ? "Error Loading Task" : "Task Not Found"}
        description={error || "The requested task could not be found."}
        iconsType="tasks"
        action={{ label: "Back to Tasks", href: "/tasks" }}
        additionAction={{ label: "Try Again", onClick: handleRefresh }}
      />
    );
  }

  const currentStatus = taskStatus?.status || task.status;
  const executionTime = taskStatus?.execution_time || "N/A";
  const startTime = taskStatus?.start_time || task.created_at || "";
  const endTime = taskStatus?.end_time;
  const rawCost =
    (taskStatus?.result as Record<string, unknown> | undefined)?.total_cost ??
    task.result?.total_cost;
  const totalCost =
    rawCost != null && !Number.isNaN(Number(rawCost)) ? Number(rawCost) : null;
  const rawBudget =
    policy?.budget?.run_budget_usd ?? task.parameters?.budget_usd;
  const budgetLimit =
    rawBudget != null && !Number.isNaN(Number(rawBudget))
      ? Number(rawBudget)
      : null;

  return (
    <>
      <div className="flex h-full w-full">
        <div className="flex h-full min-w-0 flex-1 flex-col">
          <TaskConversation
            key={task.id}
            task={task}
            currentStatus={currentStatus}
            onActivityChange={handleActivityChange}
            onRefresh={refresh}
          />
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
              isActive={conversationActivity?.streamStatus === "running"}
              startTime={startTime}
              endTime={endTime}
              executionTime={executionTime}
              activitySummary={conversationActivity?.activitySummary}
              artifacts={taskStatus?.artifacts}
              totalCost={totalCost}
              budgetLimit={budgetLimit}
              policy={policy}
            />
          }
        />
      </div>

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
                  <Loader2 className="mr-2 animate-spin" />
                  Cancelling...
                </>
              ) : (
                <>
                  <X className="mr-2" />
                  Cancel Task
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
