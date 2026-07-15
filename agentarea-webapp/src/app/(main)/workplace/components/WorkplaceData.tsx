import { getTranslations } from "next-intl/server";
import { getAgents } from "@/components/actions";
import { WorkplaceChat } from "@/components/Chat/WorkplaceChat";
import { WorkplaceOnboarding } from "@/components/Chat/WorkplaceOnboarding";
import { getProvidersAndConfigs, listPolicies, listProjects } from "@/lib/api";
import type { AgentResponse, PolicyRuleResponse, ProjectResponse } from "@/api/client/types.gen";

/**
 * Server data loader for the workplace, isolated behind a <Suspense> boundary in
 * page.tsx. The page renders its ContentBlock shell instantly; this component
 * does the (force-dynamic) Promise.all fan-out and streams the chat in once the
 * slowest of the four upstream calls resolves.
 */
export async function WorkplaceData() {
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

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-destructive">{tPage("failedToLoadAgents")}</p>
      </div>
    );
  }

  type AgentWithDisplay = AgentResponse & { icon?: string | null; color_token?: string | null };
  const agents =
    (agentsData as AgentWithDisplay[] | undefined)?.map((agent) => ({
      id: String(agent.id),
      name: agent.name,
      description: agent.description,
      icon: agent.icon ?? null,
      color_token: agent.color_token ?? null,
    })) || [];

  const projects =
    (projectsData as ProjectResponse[] | undefined)?.map((project) => ({
      id: String(project.id),
      name: project.name,
      description: project.description,
    })) || [];

  const taskPolicies =
    (policiesData as PolicyRuleResponse[] | undefined)?.map((policy) => ({
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
  const hasProviders = ((providersData as unknown as { providerConfigs?: unknown[] })?.providerConfigs?.length ?? 0) > 0;

  return (
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
  );
}

function formatPolicyName(policy: PolicyRuleResponse) {
  const effect = String(policy.effect ?? "policy");
  const target = String(policy.target ?? "*");
  return `${effect} ${target}`;
}

function formatPolicyDescription(policy: PolicyRuleResponse) {
  const subjectType = String(policy.subject_type ?? "workspace");
  const priority = Number.isFinite(policy.priority) ? policy.priority : 0;
  return `${subjectType} - priority ${priority}`;
}
