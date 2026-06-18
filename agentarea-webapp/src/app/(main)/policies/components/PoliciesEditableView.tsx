"use client";

import { useMemo } from "react";
import { useRouter } from "next/navigation";
import type { Policy } from "@/types/policies";
import PoliciesList from "./PoliciesList";

interface AgentOption {
  id: string;
  name: string;
  icon?: string | null;
  color_token?: string | null;
}

interface PoliciesEditableViewProps {
  policies: Policy[];
  agents: AgentOption[];
}

export default function PoliciesEditableView({
  policies,
  agents,
}: PoliciesEditableViewProps) {
  const router = useRouter();

  const policyById = useMemo(
    () => new Map(policies.map((p) => [p.id, p])),
    [policies]
  );

  const handleEditRule = (ruleId: string) => {
    const policy = policyById.get(ruleId);
    if (!policy) return;
    router.push(`/policies/${policy.id}`);
  };

  return (
    <>
      {policies.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-6 py-12 text-center">
          <p className="text-sm font-medium text-foreground">
            No policies yet — agents run unrestricted
          </p>
          <p className="mt-1 text-sm text-muted-foreground">
            Create a policy to start governing agent behavior. Use the New
            policy action above.
          </p>
        </div>
      ) : (
        <PoliciesList
          policies={policies}
          agents={agents}
          onEditRule={handleEditRule}
        />
      )}
    </>
  );
}
