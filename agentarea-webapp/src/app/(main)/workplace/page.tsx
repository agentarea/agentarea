import React from "react";
import { getTranslations } from "next-intl/server";
import { getAgents } from "@/components/actions";
import AuthGuard from "@/components/auth/AuthGuard";
import { WorkplaceChat } from "@/components/Chat/WorkplaceChat";
import { WorkplaceOnboarding } from "@/components/Chat/WorkplaceOnboarding";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getProvidersAndConfigs, listPolicies, listProjects } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function WorkplacePage() {
  const t = await getTranslations("Workplace.suggestions");
  const tPage = await getTranslations("WorkplacePage");

  const badgeSuggestions = [
    {
      label: t("askSpecificAgent.label"),
      text: t("askSpecificAgent.text"),
    },
    {
      label: t("analyzeProject.label"),
      text: t("analyzeProject.text"),
    },
    {
      label: t("generateDocs.label"),
      text: t("generateDocs.text"),
    },
    {
      label: t("debugIssue.label"),
      text: t("debugIssue.text"),
    },
  ];

  const [
    { data: agentsData, error },
    { data: providersData },
    { data: projectsData },
    { data: policiesData },
  ] = await Promise.all([
    getAgents(),
    getProvidersAndConfigs(),
    listProjects(),
    listPolicies({ enabled: true }),
  ]);

  const agents =
    agentsData?.map((agent: any) => ({
      id: String(agent.id),
      name: agent.name,
      description: agent.description,
    })) || [];

  const projects =
    projectsData?.map((project: any) => ({
      id: String(project.id),
      name: project.name,
      description: project.description,
    })) || [];

  const taskPolicies =
    policiesData?.map((policy: any) => ({
      id: String(policy.id),
      name: formatPolicyName(policy),
      description: formatPolicyDescription(policy),
      policy: {
        id: String(policy.id),
        target: policy.target,
        effect: policy.effect,
        params: policy.params ?? {},
      },
    })) || [];

  const defaultAgent = agents.length > 0 ? agents[0] : null;
  const hasProviders = (providersData?.providerConfigs?.length ?? 0) > 0;

  return (
    <AuthGuard>
      <ContentBlock
        header={{
          breadcrumb: [{ label: tPage("workplace"), href: "/workplace" }],
        }}
        className="p-0"
      >
        {error ? (
          <div className="flex h-full items-center justify-center">
            <p className="text-destructive">{tPage("failedToLoadAgents")}</p>
          </div>
        ) : (
          <div className="relative h-full w-full overflow-hidden">
            <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
            <div className="relative z-1 h-full p-4">
              {defaultAgent ? (
                <WorkplaceChat
                  initialAgent={defaultAgent}
                  availableAgents={agents}
                  availableProjects={projects}
                  availableTaskPolicies={taskPolicies}
                  badgeSuggestions={badgeSuggestions}
                />
              ) : (
                <WorkplaceOnboarding
                  hasProviders={hasProviders}
                  badgeSuggestions={badgeSuggestions}
                />
              )}
            </div>
          </div>
        )}
      </ContentBlock>
    </AuthGuard>
  );
}

function formatPolicyName(policy: any) {
  const effect = String(policy.effect ?? "policy");
  const target = String(policy.target ?? "*");
  return `${effect} ${target}`;
}

function formatPolicyDescription(policy: any) {
  const subjectType = String(policy.subject_type ?? "workspace");
  const priority = Number.isFinite(policy.priority) ? policy.priority : 0;
  return `${subjectType} - priority ${priority}`;
}
