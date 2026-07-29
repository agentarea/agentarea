"use client";

import React, { useCallback, useEffect, useState } from "react";
import { Bot, Check, Clock, Pause, Play, Square } from "lucide-react";
import type { ModelInstanceResponse } from "@/api/client/types.gen";
import AgentChat from "@/components/Chat/AgentChat";
import { Button } from "@/components/ui/button";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getTaskStatusPresentation } from "@/lib/status";
import {
  cancelTask,
  changeTaskModel,
  continueTask,
  getTaskStatus,
  listTaskModelOptions,
  pauseTask,
  resumeTask,
} from "./actions";

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
  const [loading, setLoading] = useState(true);
  const [modelInstances, setModelInstances] = useState<ModelInstanceResponse[]>(
    []
  );
  const [selectedModelId, setSelectedModelId] = useState<string | undefined>(
    undefined
  );
  const [changingModel, setChangingModel] = useState(false);
  const [modelApplied, setModelApplied] = useState(false);
  const [modelError, setModelError] = useState<string | null>(null);
  const [continuationIterations, setContinuationIterations] = useState("10");
  const [continuationBudget, setContinuationBudget] = useState("");
  const [continuing, setContinuing] = useState(false);
  const [continuationError, setContinuationError] = useState<string | null>(
    null
  );

  const loadTaskData = useCallback(async () => {
    setLoading(true);
    try {
      // Load task status. The conversation itself is streamed by AgentChat
      // (live events), so no separate message fetch is needed here.
      const statusResponse = await getTaskStatus(agent.id, taskId);
      if (statusResponse.data) {
        setTaskStatus(statusResponse.data as TaskStatus);
      }
    } catch {
      // Failed to load task data
    } finally {
      setLoading(false);
    }
  }, [agent.id, taskId]);

  useEffect(() => {
    loadTaskData();
  }, [loadTaskData]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await listTaskModelOptions();
        if (!cancelled && data) {
          setModelInstances(data as ModelInstanceResponse[]);
        }
      } catch {
        // Model list is optional for the page; ignore load failures.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const handleChangeModel = async (modelInstanceId: string) => {
    setSelectedModelId(modelInstanceId);
    setChangingModel(true);
    setModelApplied(false);
    setModelError(null);
    try {
      const result = await changeTaskModel(agent.id, taskId, modelInstanceId);
      if (result.error) {
        setModelError(
          "Couldn't switch model — the task isn't running anymore."
        );
      } else {
        setModelApplied(true);
      }
    } catch (error) {
      console.error("Failed to change task model:", error);
      setModelError("Couldn't switch model — please try again.");
    } finally {
      setChangingModel(false);
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

  const handleContinue = async () => {
    const iterations = Number.parseInt(continuationIterations, 10);
    const budget = continuationBudget.trim();
    if (
      !Number.isInteger(iterations) ||
      iterations < 0 ||
      (iterations === 0 && !budget)
    ) {
      setContinuationError("Grant at least one iteration or a budget top-up.");
      return;
    }

    setContinuing(true);
    setContinuationError(null);
    try {
      const result = await continueTask(
        taskId,
        iterations,
        budget || undefined
      );
      if (result.error) {
        setContinuationError(
          "The task is no longer waiting, or the grant does not lift its limit."
        );
        return;
      }
      await loadTaskData();
    } catch (error) {
      console.error("Failed to continue task:", error);
      setContinuationError("Couldn't continue the task. Please try again.");
    } finally {
      setContinuing(false);
    }
  };

  const getStatusBadge = () => {
    const status = taskStatus?.status || task?.status;
    const presentation = getTaskStatusPresentation(status || "unknown");

    return (
      <StatusIndicator
        size="sm"
        tone={presentation.tone}
        pulse={presentation.pulse}
        className="whitespace-nowrap"
      >
        {presentation.label}
      </StatusIndicator>
    );
  };

  const currentStatus = taskStatus?.status || task?.status || "";
  const isActiveTask = ["running", "paused", "blocked"].includes(currentStatus);

  // The model-switch signal only lands on a live workflow. A conversational
  // task (e.g. Telegram) writes "completed" to the DB after each reply but
  // stays alive in its follow-up window — where the live Temporal status is
  // still "running" and the model CAN be switched. Gate the switcher on that
  // live workflow status, not the DB task status, so it's available exactly
  // when it works and hidden once the workflow has actually closed.
  const isWorkflowLive = taskStatus?.status === "running";

  if (loading) {
    return (
      <div className="flex items-center justify-center py-8">
        <div className="flex items-center gap-2">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gray-400 border-t-transparent" />
          <span className="text-sm text-gray-500">Loading task...</span>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Task Header */}
      <div className="rounded-lg border border-gray-200 bg-white p-6 dark:border-gray-700 dark:bg-gray-900">
        <div className="mb-4 flex items-start justify-between">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-full bg-gradient-to-br from-gray-800 to-gray-900 shadow-sm">
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
                {currentStatus === "running" && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleTaskAction("pause")}
                  >
                    <Pause className="mr-2 h-4 w-4" />
                    Pause
                  </Button>
                )}
                {(currentStatus === "paused" ||
                  currentStatus === "blocked") && (
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => handleTaskAction("resume")}
                  >
                    <Play className="mr-2 h-4 w-4" />
                    Resume
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="destructive"
                  onClick={() => handleTaskAction("cancel")}
                >
                  <Square className="mr-2 h-4 w-4" />
                  Cancel
                </Button>
              </div>
            )}
          </div>
        </div>

        {currentStatus === "waiting_for_continuation" && (
          <div className="mb-4 space-y-3 rounded-md border border-amber-300 bg-amber-50 p-4 dark:border-amber-800 dark:bg-amber-950/30">
            <div>
              <p className="text-sm font-medium text-amber-950 dark:text-amber-100">
                This task reached its iteration or budget limit.
              </p>
              <p className="text-xs text-amber-800 dark:text-amber-300">
                Grant only the resources you want it to use. The workflow waits
                for up to 24 hours.
              </p>
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <label className="space-y-1 text-xs font-medium text-gray-700 dark:text-gray-200">
                Additional iterations
                <input
                  className="block h-9 w-32 rounded-md border border-gray-300 bg-white px-3 text-sm dark:border-gray-700 dark:bg-gray-900"
                  min="0"
                  max="1000"
                  type="number"
                  value={continuationIterations}
                  onChange={(event) =>
                    setContinuationIterations(event.target.value)
                  }
                />
              </label>
              <label className="space-y-1 text-xs font-medium text-gray-700 dark:text-gray-200">
                Budget top-up (USD, optional)
                <input
                  className="block h-9 w-44 rounded-md border border-gray-300 bg-white px-3 text-sm dark:border-gray-700 dark:bg-gray-900"
                  min="0.01"
                  step="0.01"
                  type="number"
                  value={continuationBudget}
                  onChange={(event) =>
                    setContinuationBudget(event.target.value)
                  }
                />
              </label>
              <Button size="sm" onClick={handleContinue} disabled={continuing}>
                <Play className="mr-2 h-4 w-4" />
                {continuing ? "Continuing…" : "Continue task"}
              </Button>
            </div>
            {continuationError && (
              <p className="text-xs text-red-700 dark:text-red-300">
                {continuationError}
              </p>
            )}
          </div>
        )}

        {/* On-the-fly model switch — only while the workflow is actually live
            (running, incl. the follow-up window), so the signal can land. */}
        {isWorkflowLive && modelInstances.length > 0 && (
          <div className="mb-4 flex flex-wrap items-center gap-3 rounded-md border border-gray-200 bg-gray-50 p-3 dark:border-gray-700 dark:bg-gray-800/40">
            <span className="text-xs font-medium text-gray-600 dark:text-gray-300">
              Model
            </span>
            <div className="w-64">
              <ProviderModelSelector
                modelInstances={modelInstances}
                value={selectedModelId}
                onValueChange={handleChangeModel}
                disabled={changingModel}
                placeholder="Switch model on the fly"
              />
            </div>
            {changingModel && (
              <span className="text-xs text-gray-500 dark:text-gray-400">
                Applying…
              </span>
            )}
            {!changingModel && modelApplied && !modelError && (
              <span className="flex items-center gap-1 text-xs text-green-600 dark:text-green-400">
                <Check className="h-3.5 w-3.5" />
                Applied — takes effect on the next step
              </span>
            )}
            {!changingModel && modelError && (
              <span className="text-xs text-red-600 dark:text-red-400">
                {modelError}
              </span>
            )}
          </div>
        )}

        {/* Task Details */}
        {task && (
          <div className="space-y-2">
            <div>
              <span className="text-sm font-medium text-gray-900 dark:text-gray-100">
                Description:
              </span>
              <p className="mt-1 text-sm text-gray-600 dark:text-gray-300">
                {task.description}
              </p>
            </div>
            <div className="flex gap-4 text-xs text-gray-500 dark:text-gray-400">
              <div className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                <span>
                  Created {new Date(task.created_at).toLocaleString()}
                </span>
              </div>
              {taskStatus?.start_time && (
                <div className="flex items-center gap-1">
                  <span>
                    Started {new Date(taskStatus.start_time).toLocaleString()}
                  </span>
                </div>
              )}
              {taskStatus?.end_time && (
                <div className="flex items-center gap-1">
                  <span>
                    Ended {new Date(taskStatus.end_time).toLocaleString()}
                  </span>
                </div>
              )}
            </div>
          </div>
        )}

        {/* Error Display */}
        {taskStatus?.error && (
          <div className="mt-4 rounded-lg border border-red-200 bg-red-50 p-3 dark:border-red-800 dark:bg-red-950/30">
            <p className="text-sm text-red-700 dark:text-red-300">
              {taskStatus.error}
            </p>
          </div>
        )}
      </div>

      {/* Chat Interface */}
      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white dark:border-gray-700 dark:bg-gray-900">
        <AgentChat
          agent={agent}
          taskId={taskId}
          status={taskStatus?.status || task?.status}
          className="w-full border-0"
          height="600px"
        />
      </div>
    </div>
  );
}
