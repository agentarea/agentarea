"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import {
  TaskConversation,
  type TaskConversationActivity,
} from "@/components/Chat/TaskConversation";
import EmptyState from "@/components/EmptyState";
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { Skeleton } from "@/components/ui/skeleton";
import { useTaskContext } from "./TaskContext";

export default function TaskDetailsPage() {
  const {
    task,
    taskStatus,
    taskSummary,
    policy,
    policyError,
    statusError,
    loading,
    error,
    refresh,
    setLiveStatus,
  } = useTaskContext();
  const t = useTranslations("TaskInfoPanel");
  const [, setRefreshing] = useState(false);
  const [conversationActivity, setConversationActivity] =
    useState<TaskConversationActivity | null>(null);
  const streamStatus =
    conversationActivity &&
    !conversationActivity.eventsLoading &&
    !conversationActivity.eventsError
      ? conversationActivity.streamStatus
      : null;

  // The header's task controls sit in the layout; they follow the stream.
  useEffect(() => {
    setLiveStatus(streamStatus);
  }, [setLiveStatus, streamStatus]);
  useEffect(() => () => setLiveStatus(null), [setLiveStatus]);

  const handleActivityChange = useCallback(
    (activity: TaskConversationActivity) => setConversationActivity(activity),
    []
  );

  const handleRefresh = async () => {
    setRefreshing(true);
    await refresh();
    setRefreshing(false);
  };

  if (loading) {
    return (
      <div
        className="mx-auto w-full max-w-3xl space-y-4 p-4"
        aria-hidden="true"
      >
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

  const currentStatus = streamStatus ?? (taskStatus?.status || task.status);
  const executionStatus =
    conversationActivity?.executionStatus ?? taskStatus?.execution_status;
  const durationMs = taskSummary?.duration_ms;
  const summaryExecutionTime =
    typeof durationMs === "number" && Number.isFinite(durationMs)
      ? `${(durationMs / 1000).toFixed(1)}s`
      : null;
  const reportedExecutionTime = taskStatus?.execution_time;
  let executionTime =
    summaryExecutionTime ??
    (reportedExecutionTime && reportedExecutionTime !== "N/A"
      ? reportedExecutionTime
      : "N/A");
  if (executionTime === "N/A" && currentStatus === "running") {
    executionTime = t("executionInProgress");
  } else if (
    executionTime === "N/A" &&
    currentStatus === "completed" &&
    executionStatus === "waiting"
  ) {
    executionTime = t("executionAwaitingFollowUp");
  }
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
                provenance: task.provenance,
              }}
              currentStatus={currentStatus}
              executionStatus={executionStatus}
              isActive={
                currentStatus === "running" &&
                conversationActivity?.executionStatus === "running"
              }
              startTime={startTime}
              endTime={endTime}
              executionTime={executionTime}
              activitySummary={conversationActivity?.activitySummary}
              artifacts={taskStatus?.artifacts}
              totalCost={totalCost}
              budgetLimit={budgetLimit}
              policy={policy}
              policyError={policyError}
              statusError={statusError}
            />
          }
        />
      </div>

    </>
  );
}
