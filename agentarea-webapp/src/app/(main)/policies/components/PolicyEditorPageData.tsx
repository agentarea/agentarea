import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState";
import { listAgents, listPolicies } from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type { Policy } from "@/types/policies";
import PolicyEditor, { type PolicyEditorTarget } from "./PolicyEditor";

interface AgentLike {
  id: string;
  name: string;
  icon?: string | null;
  color_token?: string | null;
}

interface PolicyEditorPageDataProps {
  policyId?: string;
}

export async function PolicyEditorPageData({
  policyId,
}: PolicyEditorPageDataProps) {
  let policies: Policy[] = [];
  let agents: AgentLike[] = [];
  let policiesError: string | null = null;

  const [policiesRes, agentsRes, authContext] = await Promise.all([
    listPolicies().catch((reason) => ({ data: null, error: reason })),
    listAgents().catch((reason) => ({ data: null, error: reason })),
    getAuthContext(),
  ]);

  if (policiesRes.error) {
    console.error("Failed to fetch policies:", policiesRes.error);
    policiesError = "Failed to load policies";
  } else {
    policies = ((policiesRes.data as Policy[] | null) ?? []) as Policy[];
  }

  if (agentsRes.error) {
    console.error("Failed to load agents for policy editor:", agentsRes.error);
  } else {
    agents = ((agentsRes.data as AgentLike[] | null) ?? []).map((agent) => ({
      id: agent.id,
      name: agent.name,
      icon: agent.icon,
      color_token: agent.color_token,
    }));
  }

  const target = resolveTarget({ policyId, policies });
  if (!target) notFound();

  const title = policyId ? "Edit policy rule" : "New policy rule";

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Policies", href: "/policies" },
          { label: title },
        ],
      }}
    >
      <div className="main-content">
        {policiesError && policyId ? (
          <EmptyState
            title="Couldn't load policy"
            description={policiesError}
            iconsType="audit"
          />
        ) : (
          <PolicyEditor
            target={target}
            agents={agents}
            workspaceId={authContext.workspaceId}
          />
        )}
      </div>
    </ContentBlock>
  );
}

function resolveTarget({
  policyId,
  policies,
}: {
  policyId?: string;
  policies: Policy[];
}): PolicyEditorTarget | null {
  if (policyId) {
    const policy = policies.find((item) => item.id === policyId);
    return policy ? { mode: "edit", policy } : null;
  }

  return { mode: "create-workspace" };
}
