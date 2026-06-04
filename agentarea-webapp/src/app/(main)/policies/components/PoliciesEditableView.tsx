"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { GovernancePolicy } from "@/types/policies";
import PolicyEditor, { type PolicyEditorTarget } from "./PolicyEditor";
import {
  type ConfiguredPolicyCard,
  PolicyRulesView,
} from "./PolicyRulesView";

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
  baseline: ConfiguredPolicyCard["rules"];
  configured: ConfiguredPolicyCard[];
  policies: GovernancePolicy[];
  agents: AgentOption[];
  workspaceId: string | null;
  hasWorkspacePolicy: boolean;
}

export default function PoliciesEditableView({
  baseline,
  configured,
  policies,
  agents,
  workspaceId,
  hasWorkspacePolicy,
}: PoliciesEditableViewProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<PolicyEditorTarget | null>(null);

  const openCreate = () => {
    // No workspace policy yet → default new policies to workspace scope so the
    // header action lines up with the baseline card's "Set workspace policy".
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

  const handleEdit = (policyId: string) => {
    const policy = policies.find((p) => p.id === policyId);
    if (!policy) return;
    setTarget({ mode: "edit", policy });
    setOpen(true);
  };

  const handleSetWorkspacePolicy = () => {
    setTarget({ mode: "create-workspace" });
    setOpen(true);
  };

  return (
    <>
      <PolicyRulesView
        baseline={baseline}
        policies={configured}
        hasWorkspacePolicy={hasWorkspacePolicy}
        onEdit={handleEdit}
        onSetWorkspacePolicy={handleSetWorkspacePolicy}
      />
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
