import { getTranslations } from "next-intl/server";
import { getAgents } from "@/components/actions";
import { WorkplaceChat } from "@/components/Chat/WorkplaceChat";
import { WorkplaceOnboarding } from "@/components/Chat/WorkplaceOnboarding";
import { getProvidersAndConfigs, listPolicies, listProjects } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getViewerCapabilities } from "@/lib/workspace-context";
import type {
  AgentResponse,
  PolicyRuleResponse,
  ProjectResponse,
} from "@/api/client/types.gen";
import { loadWorkplaceSuggestions } from "./loadWorkplaceSuggestions";

/**
 * Server data loader for the workplace, isolated behind a <Suspense> boundary in
 * page.tsx. The page renders its ContentBlock shell instantly; this component
 * streams the chat in once the reads it genuinely blocks on resolve.
 *
 * Three groups, not one fan-out, because they are not owed to the user at the
 * same time:
 *  - these three decide whether the workplace can be used at all, so the first
 *    paint waits for them and they go together;
 *  - the provider list only answers a question the onboarding screen asks, so
 *    it is read only when there are no agents;
 *  - the starter chips are a prompt, so their promise is handed down unawaited
 *    and a <Suspense> fills them in afterwards.
 */
export async function WorkplaceData() {
  const [tPage, tAdmin, { canAdminister }] = await Promise.all([
    getTranslations("WorkplacePage"),
    getTranslations("AdminOnly"),
    getViewerCapabilities(),
  ]);

  const [{ data: agentsData, error }, { data: projectsData }, policiesRes] =
    await Promise.all([
      getAgents(),
      listProjects(),
      canAdminister ? listPolicies({ enabled: true }) : null,
    ]);

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-destructive">{tPage("failedToLoadAgents")}</p>
      </div>
    );
  }

  type AgentWithDisplay = AgentResponse & { icon?: string | null };
  const agents =
    (agentsData as AgentWithDisplay[] | undefined)?.map((agent) => ({
      id: String(agent.id),
      name: agent.name,
      description: agent.description,
      icon: agent.icon ?? null,
    })) || [];

  const projects =
    (projectsData as ProjectResponse[] | undefined)?.map((project) => ({
      id: String(project.id),
      name: project.name,
      description: project.description,
    })) || [];

  let policiesNotice: { text: string; isError: boolean } | null = null;
  if (!policiesRes) {
    policiesNotice = { text: tAdmin("hints.pickTaskPolicy"), isError: false };
  } else if (policiesRes.error || !policiesRes.data) {
    console.error("Failed to load task policies", policiesRes.error);
    policiesNotice = {
      text: apiErrorMessage(policiesRes, tPage("policiesLoadFailed")),
      isError: true,
    };
  }

  const taskPolicies =
    (policiesRes?.data as PolicyRuleResponse[] | undefined)?.map((policy) => ({
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

  // Deliberately not awaited: the chat renders now, the chips arrive after.
  const badgeSuggestions = loadWorkplaceSuggestions(
    agents.map((agent) => agent.name)
  );

  const defaultAgent = agents.length > 0 ? agents[0] : null;

  // Only the onboarding screen asks whether a provider exists, and it is the
  // screen nobody sees twice — so the read happens on that branch alone
  // instead of on every visit to a working workplace.
  const body = defaultAgent ? (
    <WorkplaceChat
      initialAgent={defaultAgent}
      availableAgents={agents}
      availableProjects={projects}
      availableTaskPolicies={taskPolicies}
      badgeSuggestions={badgeSuggestions}
    />
  ) : (
    <WorkplaceOnboarding
      hasProviders={await hasAnyProvider()}
      badgeSuggestions={badgeSuggestions}
    />
  );

  return (
    <div className="relative h-full w-full overflow-hidden">
      <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
      <div className="relative z-1 flex h-full flex-col p-4">
        <div className="min-h-0 flex-1">{body}</div>
        {defaultAgent && policiesNotice && (
          <p
            role={policiesNotice.isError ? "alert" : undefined}
            className={
              policiesNotice.isError
                ? "shrink-0 pt-2 text-center text-xs text-destructive"
                : "shrink-0 pt-2 text-center text-xs text-muted-foreground"
            }
          >
            {policiesNotice.text}
          </p>
        )}
      </div>
    </div>
  );
}

async function hasAnyProvider(): Promise<boolean> {
  const { data } = await getProvidersAndConfigs();
  const configs = (data as unknown as { providerConfigs?: unknown[] })
    ?.providerConfigs;
  return (configs?.length ?? 0) > 0;
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
