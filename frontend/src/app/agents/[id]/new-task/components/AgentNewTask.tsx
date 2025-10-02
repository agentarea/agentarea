"use client";

import React, { useState } from "react";
import { Agent } from "@/types/agent";
import FullChat from "@/components/Chat/FullChat";
import TaskDetails from "./TaskDetails";
import { useTranslations } from "next-intl";

interface Props {
  agent: Agent;
}

export default function AgentNewTask({ agent }: Props) {
  const [isTaskRunning, setIsTaskRunning] = useState(false);
  const [isTaskActive, setIsTaskActive] = useState(false);
  const t = useTranslations("Agent.descriptionPage");

  // Handle task creation from chat
  const handleTaskCreated = (taskId: string) => {
    setIsTaskActive(true);
    setIsTaskRunning(true);
  };

  // Handle task completion
  const handleTaskFinished = (taskId: string) => {
    setIsTaskRunning(false);
  };

  return (
    <div className="flex flex-row items-start h-full w-full overflow-hidden gap-3 max-w-7xl mx-auto">
      <div className="py-5 pl-3 h-full w-full overflow-hidden">
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
      </div>
      <TaskDetails agent={agent} isTaskRunning={isTaskRunning} isTaskActive={isTaskActive} />
    </div>
  );
}
