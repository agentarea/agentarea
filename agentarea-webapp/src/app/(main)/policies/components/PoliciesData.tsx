import EmptyState from "@/components/EmptyState";
import {
  listAgents,
  listGovernancePolicies,
  previewEffectivePolicy,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type {
  EffectivePolicyResponse,
  GovernancePolicy,
} from "@/types/policies";
import PoliciesEditableView from "./PoliciesEditableView";
import { documentToRules, scopeLabel } from "./policy-rules";
import type { ConfiguredPolicyCard } from "./PolicyRulesView";

interface AgentLike {
  id: string;
  name: string;
}

export async function PoliciesData() {
  let policies: GovernancePolicy[] = [];
  let baselineRules: ConfiguredPolicyCard["rules"] = [];
  let agents: AgentLike[] = [];
  let policiesError: string | null = null;

  const [policiesRes, effectiveRes, agentsRes, authContext] =
    await Promise.all([
      listGovernancePolicies().catch((reason) => ({ data: null, error: reason })),
      previewEffectivePolicy().catch((reason) => ({ data: null, error: reason })),
      listAgents().catch((reason) => ({ data: null, error: reason })),
      getAuthContext(),
    ]);

  if (policiesRes.error) {
    console.error("Failed to fetch governance policies:", policiesRes.error);
    policiesError = "Failed to load policies";
  } else {
    policies = ((policiesRes.data as GovernancePolicy[] | null) ??
      []) as GovernancePolicy[];
  }

  if (effectiveRes.error) {
    console.error("Failed to resolve effective policy:", effectiveRes.error);
  } else {
    const effective = (effectiveRes.data as EffectivePolicyResponse | null)
      ?.effective_policy;
    baselineRules = documentToRules(effective);
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
  if (policiesError && baselineRules.length === 0 && policies.length === 0) {
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

  const configured: ConfiguredPolicyCard[] = policies.map((p) => ({
    id: p.id,
    title: scopeLabel(p.scope_type, p.scope_id),
    enabled: p.enabled,
    rules: documentToRules(p.document),
  }));

  const hasWorkspacePolicy = policies.some(
    (p) => p.scope_type === "workspace"
  );

  return (
    <div className="space-y-4">
      <PoliciesEditableView
        baseline={baselineRules}
        configured={configured}
        policies={policies}
        agents={agents}
        workspaceId={authContext.workspaceId}
        hasWorkspacePolicy={hasWorkspacePolicy}
      />
    </div>
  );
}
