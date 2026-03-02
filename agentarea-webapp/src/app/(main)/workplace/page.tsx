import React from "react";
import AuthGuard from "@/components/auth/AuthGuard";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getAgents } from "@/components/actions";
import { WorkplaceChat } from "@/components/Chat/WorkplaceChat";
import { getTranslations } from "next-intl/server";

export const dynamic = "force-dynamic";

export default async function WorkplacePage() {
  const t = await getTranslations("Workplace.suggestions");

  const badgeSuggestions = [
    { 
      label: t("askSpecificAgent.label"), 
      text: t("askSpecificAgent.text") 
    },
    { 
      label: t("analyzeProject.label"), 
      text: t("analyzeProject.text") 
    },
    { 
      label: t("generateDocs.label"), 
      text: t("generateDocs.text") 
    },
    { 
      label: t("debugIssue.label"), 
      text: t("debugIssue.text") 
    },
  ];

  // Fetch agents server-side
  const { data: agentsData, error } = await getAgents();

  const agents = agentsData?.map((agent: any) => ({
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
        className="p-0"
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
          <div className="relative h-full w-full overflow-hidden">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 h-full p-4">
              <WorkplaceChat
                initialAgent={defaultAgent}
                availableAgents={agents}
                badgeSuggestions={badgeSuggestions}
              />
            </div>
          </div>
        )}
      </ContentBlock>
    </AuthGuard>
  );
}
