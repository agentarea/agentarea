"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import type { Policy } from "@/types/policies";
import PolicyEditor, { type PolicyEditorTarget } from "./PolicyEditor";
import PoliciesList from "./PoliciesList";

// Custom event dispatched by the header "New policy" control. The header button
// lives in a separate React tree (page-level controls slot), so we bridge it to
// this client component via a window event — mirroring how the Access view
// reaches into the DOM for its primary action.
export const NEW_POLICY_EVENT = "policies:new";

interface AgentOption {
  id: string;
  name: string;
}

interface PoliciesEditableViewProps {
  policies: Policy[];
  agents: AgentOption[];
  workspaceId: string | null;
  hasWorkspacePolicy: boolean;
}

export default function PoliciesEditableView({
  policies,
  agents,
  workspaceId,
  hasWorkspacePolicy,
}: PoliciesEditableViewProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<PolicyEditorTarget | null>(null);

  const policyById = useMemo(
    () => new Map(policies.map((p) => [p.id, p])),
    [policies]
  );

  const openCreate = () => {
    // No workspace policy yet → default new rules to workspace scope.
    setTarget(
      hasWorkspacePolicy ? { mode: "create-agent" } : { mode: "create-workspace" }
    );
    setOpen(true);
  };

  useEffect(() => {
    const handler = () => openCreate();
    window.addEventListener(NEW_POLICY_EVENT, handler);
    return () => window.removeEventListener(NEW_POLICY_EVENT, handler);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hasWorkspacePolicy]);

  const handleEditRule = (ruleId: string) => {
    const policy = policyById.get(ruleId);
    if (!policy) return;
    setTarget({ mode: "edit", policy });
    setOpen(true);
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
      <PolicyEditor
        open={open}
        onOpenChange={setOpen}
        target={target}
        agents={agents}
        workspaceId={workspaceId}
        onSaved={() => router.refresh()}
      />
    </>
  );
}
