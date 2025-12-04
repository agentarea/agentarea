import React from "react";
import AuthGuard from "@/components/auth/AuthGuard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { WorkplaceChat } from "@/components/Chat/WorkplaceChat";
import { getAgents } from "@/components/actions";

export default async function WorkplacePage() {
  const badgeSuggestions = [
    { label: "Create new agent for my project", text: "Create new agent for my project" },
    { label: "Add task for agent", text: "Create new task for agent - @" },
    { label: "Ask agent about my project", text: "Ask agent about my project" },
    { label: "Something about my project", text: "Something about my project" },
    { label: "Test test :)", text: "Test test lala" },
  ];

  // Fetch agents server-side
  const { data: agentsData, error } = await getAgents();

  const agents = agentsData?.map((agent) => ({
    id: String(agent.id),
    name: agent.name,
    description: agent.description,
  })) || [];

  // Select first agent as default
  const defaultAgent = agents.length > 0 ? agents[0] : null;

  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: "Workplace", href: "/workplace" }],
        }}
      >
        {error ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-destructive">Failed to load agents</p>
          </div>
        ) : !defaultAgent ? (
          <div className="flex h-full items-center justify-center">
            <div className="text-center">
              <p className="text-muted-foreground">No agents available.</p>
              <p className="text-sm text-muted-foreground">Create your first agent to get started.</p>
            </div>
          </div>
        ) : (
          <WorkplaceChat
            initialAgent={defaultAgent}
            availableAgents={agents}
            badgeSuggestions={badgeSuggestions}
          />
        )}
      </ContentBlock>
    </AuthGuard>
  );
}
