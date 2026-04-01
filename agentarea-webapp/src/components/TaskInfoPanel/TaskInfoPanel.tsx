"use client";

import { useState } from "react";
import { InfoPanelBody, InfoPanelShell } from "@/components/InfoPanel";
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
      <InfoPanelShell>
        <InfoPanelBody className="space-y-3">
          <ModelInfo agentId={agentId} />
        </InfoPanelBody>
      </InfoPanelShell>
    );
  }

  if (!task) {
    return null;
  }

  return (
    <InfoPanelShell>
      <TaskInfoHeader task={task} currentStatus={currentStatus} />
      <TaskInfoTabs activeTab={activeTab} setActiveTab={setActiveTab} />
      <InfoPanelBody className="space-y-1.5">
        {activeTab === "overview" && (
          <>
            <KeyMetrics
              currentStatus={currentStatus}
              isActive={isActive}
              executionTime={executionTime}
              formattedStart={formattedStart}
              formattedEnd={formattedEnd}
            />

            <Metadata task={task} />
            <QuickActions task={task} />
          </>
        )}

        {activeTab === "model" && <ModelInfo task={task} />}
      </InfoPanelBody>
    </InfoPanelShell>
  );
}
