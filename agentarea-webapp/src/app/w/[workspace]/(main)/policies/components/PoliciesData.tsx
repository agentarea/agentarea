import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { listAgents, listPolicies } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import type { Policy } from "@/types/policies";
import PoliciesEditableView from "./PoliciesEditableView";

interface AgentLike {
  id: string;
  name: string;
  icon?: string | null;
}

export async function PoliciesData() {
  let agents: AgentLike[] = [];

  const [policiesRes, agentsRes] = await Promise.all([
    listPolicies().catch((reason) => ({
      data: null,
      error: reason,
      status: undefined,
    })),
    listAgents().catch((reason) => ({ data: null, error: reason })),
  ]);

  if (policiesRes.error) {
    console.error("Failed to fetch policies:", policiesRes.error);
    return (
      <div className="space-y-4">
        <RetryEmptyState
          title="Couldn't load policies"
          description={apiErrorMessage(policiesRes, "Failed to load policies")}
          iconsType="audit"
        />
      </div>
    );
  }
  const policies = (policiesRes.data as Policy[] | null) ?? [];

  if (agentsRes.error) {
    console.error("Failed to load agents for policy editor:", agentsRes.error);
  } else {
    agents = ((agentsRes.data as AgentLike[] | null) ?? []).map((a) => ({
      id: a.id,
      name: a.name,
      icon: a.icon,
    }));
  }

  return <PoliciesEditableView policies={policies} agents={agents} />;
}
