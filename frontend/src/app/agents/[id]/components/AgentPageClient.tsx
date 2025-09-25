"use client";

import React, { useState } from "react";
import { Agent } from "@/types/agent";
import AgentDetails from "./AgentDetails";
import FullChat from "@/components/Chat/FullChat";
import TaskDetails from "./TaskDetails";
import { useTranslations } from "next-intl";

interface Props {
  agent: Agent;
}

export default function AgentPageClient({ agent }: Props) {
  const [isTaskRunning, setIsTaskRunning] = useState(false);
  const [isTaskActive, setIsTaskActive] = useState(false);
  const t = useTranslations("Agent.descriptionPage");
  // Handle task creation from chat
  const handleTaskCreated = (taskId: string) => {
    console.log("Task created", taskId);
    setIsTaskActive(true);
    setIsTaskRunning(true);
  };

  // Handle task completion
  const handleTaskFinished = (taskId: string) => {
    console.log("Task finished", taskId);
    setIsTaskRunning(false);
  };

  return (
    <div className="flex flex-row items-start h-full w-full overflow-hidden gap-3 max-w-7xl mx-auto">
      {/* <AgentDetails agent={agent} isTaskRunning={isTaskRunning} /> */}
      <FullChat
        placeholder={t("placeholderNewTask", { agentName: agent.name })}
        agent={{
          id: agent.id,
          name: agent.name,
          description: agent.description || undefined
        }}
        onTaskStarted={handleTaskCreated}
        onTaskFinished={handleTaskFinished}
      />
      <TaskDetails agent={agent} isTaskRunning={isTaskRunning} isTaskActive={isTaskActive} />
    </div>
  );
}
