"use client";

import React, { useState } from "react";
import { useRouter, usePathname, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import FullChat from "@/components/Chat/FullChat";
import { Agent } from "@/types/agent";
import TaskDetails from "./TaskDetails";

interface Props {
  agent: Agent;
}

export default function AgentNewTask({ agent }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const [isTaskRunning, setIsTaskRunning] = useState(false);
  const [isTaskActive, setIsTaskActive] = useState(false);
  const t = useTranslations("AgentsPage.descriptionPage");

  // Handle task creation from chat
  const handleTaskCreated = (taskId: string) => {
    setIsTaskActive(true);
    setIsTaskRunning(true);
    // Change path to /tasks/[id] without navigation
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/tasks/${taskId}`);
    }
  };

  // Handle task completion
  const handleTaskFinished = (taskId: string) => {
    setIsTaskRunning(false);
  };

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-row items-start gap-3 overflow-hidden">
      <div className="h-full w-full overflow-hidden py-5 pl-3 relative">
        <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 h-full">
              <FullChat
                placeholder={t("placeholderNewTask", { agentName: agent.name })}
                agent={{
                  id: agent.id,
                  name: agent.name,
                  description: agent.description || undefined,
                }}
                onTaskStarted={handleTaskCreated}
                onTaskFinished={handleTaskFinished}
              />
            </div>
      </div>
      <TaskDetails
        agent={agent}
        isTaskRunning={isTaskRunning}
        isTaskActive={isTaskActive}
      />
    </div>
  );
}
