"use client";

import React from "react";
import { useTranslations } from "next-intl";
import { Sparkles } from "lucide-react";
import { ChatWelcome } from "@/components/Chat/componets/ChatWelcome";
import FullChat from "@/components/Chat/FullChat";
import TaskInfoPanel from "@/components/TaskInfoPanel/TaskInfoPanel";
import TaskInfoPanelDock from "@/components/TaskInfoPanel/TaskInfoPanelDock";
import { Agent } from "@/types/agent";

interface Props {
  agent: Agent;
}

export default function AgentNewTask({ agent }: Props) {
  const t = useTranslations("AgentsPage.descriptionPage");

  // Handle task creation from chat
  const handleTaskCreated = (taskId: string) => {
    // Change path to /tasks/[id] without navigation
    if (typeof window !== "undefined") {
      window.history.replaceState(null, "", `/tasks/${taskId}`);
    }
  };

  // Handle task completion
  const handleTaskFinished = (taskId: string) => {
    void taskId;
  };

  const welcomeComponent = (
    <ChatWelcome
      icon={Sparkles}
      variant="neutral"
      size="sm"
      animate={false}
      titleClassName="text-muted-foreground opacity-70"
      title={t("titleNewTask", { agentName: agent.name })}
    />
  );

  return (
    <div className="mx-auto flex h-full w-full max-w-7xl flex-row items-start gap-3 overflow-hidden">
      <div className="h-full w-full overflow-hidden py-5 pl-3 relative">
        <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
        <div className="relative z-1 h-full">
          <FullChat
            welcomeComponent={welcomeComponent}
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
      <TaskInfoPanelDock panel={<TaskInfoPanel agentId={agent.id} />} />
    </div>
  );
}
