"use client";

import React, { useState } from "react";
import { Agent } from "@/types/agent";
import AgentDetails from "./AgentDetails";
import FullChat from "@/components/Chat/FullChat";

interface Props {
  agent: Agent;
}

export default function AgentPageClient({ agent }: Props) {
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
      <AgentDetails agent={agent} isTaskRunning={isTaskRunning} />
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
