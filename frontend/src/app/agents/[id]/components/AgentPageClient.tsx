"use client";

import React, { useState } from "react";
import { Agent } from "@/types/agent";
import AgentDetails from "./AgentDetails";
import FullChat from "@/components/Chat/FullChat";

interface ModelInfo {
  provider_name?: string;
  model_display_name?: string;
  config_name?: string;
}

interface Props {
  agent: Agent;
  modelInfo: ModelInfo | null;
}

export default function AgentPageClient({ agent, modelInfo }: Props) {
  const [isTaskRunning, setIsTaskRunning] = useState(false);

  // Handle task creation from chat
  const handleTaskCreated = (taskId: string) => {
    console.log("Task created", taskId);
    setIsTaskRunning(true);
  };

  // Handle task completion
  const handleTaskFinished = (taskId: string) => {
    console.log("Task finished", taskId);
    setIsTaskRunning(false);
  };

  return (
    <div className="flex flex-col h-full w-full overflow-hidden">
      <AgentDetails agent={agent} modelInfo={modelInfo} isTaskRunning={isTaskRunning} />
      <FullChat
        agent={{
          id: agent.id,
          name: agent.name,
          description: agent.description || undefined
        }}
        onTaskStarted={handleTaskCreated}
        onTaskFinished={handleTaskFinished}
      />
    </div>
  );
}
