import EmptyState from "@/components/EmptyState";
import { listAgents, listPolicies } from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type { Policy } from "@/types/policies";
import PoliciesEditableView from "./PoliciesEditableView";

interface AgentLike {
  id: string;
  name: string;
}

export async function PoliciesData() {
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
    agents = ((agentsRes.data as AgentLike[] | null) ?? []).map((a) => ({
      id: a.id,
      name: a.name,
    }));
  }

  // Hard failure only when we have nothing to show at all.
  if (policiesError && policies.length === 0) {
    return (
      <div className="space-y-4">
        <EmptyState
          title="Couldn't load policies"
          description={policiesError}
          iconsType="audit"
        />
      </div>
    );
  }

  const hasWorkspacePolicy = policies.some(
    (p) => p.subject_type === "workspace"
  );

  return (
    <PoliciesEditableView
      policies={policies}
      agents={agents}
      workspaceId={authContext.workspaceId}
      hasWorkspacePolicy={hasWorkspacePolicy}
    />
  );
}
