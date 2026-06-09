import EmptyState from "@/components/EmptyState";
import {
  getRebacGraph,
  listAgents,
  listPolicies,
  previewEffectivePolicy,
} from "@/lib/api";
import { getAuthContext } from "@/lib/getAuthContext";
import type {
  EffectivePolicyResponse,
  Policy,
  PolicyRule,
} from "@/types/policies";
import PoliciesEditableView from "./PoliciesEditableView";
import { documentToRules } from "./policy-rules";

interface AgentLike {
  id: string;
  name: string;
}

export async function PoliciesData() {
  let policies: Policy[] = [];
  let baselineRules: PolicyRule[] = [];
  let agents: AgentLike[] = [];
  let policiesError: string | null = null;

  // getRebacGraph powers the Access view's Keto-sourced tool access; we fetch it
  // here so the Policies view stays in lockstep with that integration even
  // though the approved matrix surfaces tool access via the Tools column +
  // Access-view link rather than rendering the graph inline.
  const [policiesRes, effectiveRes, agentsRes, , authContext] =
    await Promise.all([
      listPolicies().catch((reason) => ({ data: null, error: reason })),
      previewEffectivePolicy().catch((reason) => ({
        data: null,
        error: reason,
      })),
      listAgents().catch((reason) => ({ data: null, error: reason })),
      getRebacGraph().catch(() => ({ data: null, error: null })),
      getAuthContext(),
    ]);

  if (policiesRes.error) {
    console.error("Failed to fetch policies:", policiesRes.error);
    policiesError = "Failed to load policies";
  } else {
    policies = ((policiesRes.data as Policy[] | null) ?? []) as Policy[];
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

  const hasWorkspacePolicy = policies.some(
    (p) => p.subject_type === "workspace"
  );

  return (
    <div className="space-y-4">
      <PoliciesEditableView
        baseline={baselineRules}
        policies={policies}
        agents={agents}
        workspaceId={authContext.workspaceId}
        hasWorkspacePolicy={hasWorkspacePolicy}
      />
    </div>
  );
}
