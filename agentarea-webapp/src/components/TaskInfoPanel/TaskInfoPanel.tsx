"use client";

import { useState } from "react";
import TaskInfoHeader from "./components/TaskInfoHeader";
import TaskInfoTabs from "./components/TaskInfoTabs";
import KeyMetrics from "./components/KeyMetrics";
import QuickActions from "./components/QuickActions";
import Metadata from "./components/Metadata";
import ModelInfo from "./components/ModelInfo";
import { Task } from "./types";

interface TaskInfoPanelProps {
  task?: Task | null;
  agentId?: string; // Optional agentId if no task
  currentStatus?: string;
  isActive?: boolean;
  startTime?: string;
  endTime?: string;
  executionTime?: string;
}

export default function TaskInfoPanel({
  task,
  agentId,
  currentStatus = "unknown",
  isActive = false,
  startTime = "",
  endTime,
  executionTime = "N/A",
}: TaskInfoPanelProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "model">("overview");
  const formattedStart = startTime
    ? new Date(startTime).toLocaleString()
    : "N/A";
  const formattedEnd = endTime ? new Date(endTime).toLocaleString() : "—";

  // If we have no task but have an agentId, we show ModelInfo directly (Agent Info mode)
  if (!task && agentId) {
    return (
      <div className="h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700">
        <div className="h-full bg-white dark:bg-zinc-800">
           <div className="space-y-3 px-3.5 py-3 text-xs">
             <ModelInfo agentId={agentId} />
           </div>
        </div>
      </div>
    );
  }

  if (!task) {
    return null;
  }

  return (
    <div className="h-full overflow-auto border-l border-zinc-200 dark:border-zinc-700">
      <div className="h-full bg-white dark:bg-zinc-800">
        {/* Header */}
        <TaskInfoHeader task={task} currentStatus={currentStatus} />

        {/* Tabs */}
        <TaskInfoTabs activeTab={activeTab} setActiveTab={setActiveTab} />

        {/* Content sections */}
        <div className="space-y-1.5 px-3.5 py-3 text-xs">
          {activeTab === "overview" && (
            <>
              {/* Key metrics */}
              <KeyMetrics
                currentStatus={currentStatus}
                isActive={isActive}
                executionTime={executionTime}
                formattedStart={formattedStart}
                formattedEnd={formattedEnd}
              />

              {/* Metadata */}
              <Metadata task={task} />

              {/* Quick links / actions */}
              <QuickActions task={task} />
            </>
          )}

          {activeTab === "model" && <ModelInfo task={task} />}
        </div>
      </div>
    </div>
  );
}
