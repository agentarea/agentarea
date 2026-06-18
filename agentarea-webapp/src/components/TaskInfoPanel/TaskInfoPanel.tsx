"use client";

import { useState } from "react";
import { useLocale } from "next-intl";
import { InfoPanelBody, InfoPanelShell } from "@/components/InfoPanel";
import TaskInfoHeader from "./components/TaskInfoHeader";
import TaskInfoTabs from "./components/TaskInfoTabs";
import KeyMetrics from "./components/KeyMetrics";
import QuickActions from "./components/QuickActions";
import Metadata from "./components/Metadata";
import ModelInfo from "./components/ModelInfo";
import ActivitySummary, { TaskActivitySummary } from "./components/ActivitySummary";
import Participants from "./components/Participants";
import Files from "./components/Files";
import Documents from "./components/Documents";
import BudgetInfo from "./components/BudgetInfo";
import PolicyInfo from "./components/PolicyInfo";
import { Task } from "./types";
import type { EffectivePolicy } from "@/types/policies";

interface TaskInfoPanelProps {
  task?: Task | null;
  agentId?: string; // Optional agentId if no task
  currentStatus?: string;
  isActive?: boolean;
  startTime?: string;
  endTime?: string;
  executionTime?: string;
  activitySummary?: TaskActivitySummary;
  artifacts?: unknown[];
  totalCost?: number | null;
  budgetLimit?: number | null;
  policy?: EffectivePolicy | null;
}

export default function TaskInfoPanel({
  task,
  agentId,
  currentStatus = "unknown",
  isActive = false,
  startTime = "",
  endTime,
  executionTime = "N/A",
  activitySummary,
  artifacts,
  totalCost,
  budgetLimit,
  policy,
}: TaskInfoPanelProps) {
  const [activeTab, setActiveTab] = useState<"overview" | "model">("overview");
  const locale = useLocale();

  const formattedStart = startTime
    ? new Date(startTime).toLocaleString(locale)
    : "N/A";
  const formattedEnd = endTime ? new Date(endTime).toLocaleString(locale) : "—";

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

            {(totalCost != null || budgetLimit != null) && (
              <BudgetInfo
                totalCost={totalCost ?? 0}
                budgetLimit={budgetLimit ?? null}
              />
            )}

            <PolicyInfo policy={policy} />

            <ActivitySummary summary={activitySummary} />
            <Participants
              agentName={task.agent_name}
              delegatedAgents={activitySummary?.delegatedAgents}
            />
            <Files files={activitySummary?.files} />
            <Documents artifacts={artifacts} />
            <Metadata task={task} />
            <QuickActions task={task} />
          </>
        )}

        {activeTab === "model" && <ModelInfo task={task} isActive={isActive} />}
      </InfoPanelBody>
    </InfoPanelShell>
  );
}
