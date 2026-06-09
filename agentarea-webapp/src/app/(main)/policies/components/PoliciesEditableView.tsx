"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { Policy, PolicyRule } from "@/types/policies";
import PolicyEditor, { type PolicyEditorTarget } from "./PolicyEditor";
import PoliciesMatrix, { type AddRuleScope } from "./PoliciesMatrix";
import { policiesToMatrix } from "./policy-rules";

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
  baseline: PolicyRule[];
  policies: Policy[];
  agents: AgentOption[];
  workspaceId: string | null;
  hasWorkspacePolicy: boolean;
}

// Slim one-line note that the workspace policy (the matrix's first row) is
// inherited by every agent. When no workspace policy exists yet, it doubles as
// the prompt to set one. Understated — the matrix is the focus.
function BaselineStrip({
  baseline,
  hasWorkspacePolicy,
  onSetWorkspacePolicy,
}: {
  baseline: PolicyRule[];
  hasWorkspacePolicy: boolean;
  onSetWorkspacePolicy: () => void;
}) {
  const count = baseline.length;
  const summary = hasWorkspacePolicy
    ? `Workspace policy is inherited by all agents · ${count} effective restriction${
        count === 1 ? "" : "s"
      }`
    : "No workspace policy — agents are governed only by their own policies";

  return (
    <div className="flex items-center gap-2 rounded-md border border-dashed border-border bg-muted/20 px-3 py-2 text-xs text-muted-foreground">
      <span>{summary}</span>
      {!hasWorkspacePolicy && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="ml-auto gap-1.5"
          onClick={onSetWorkspacePolicy}
        >
          <Plus className="h-3.5 w-3.5" />
          Set workspace policy
        </Button>
      )}
    </div>
  );
}

export default function PoliciesEditableView({
  baseline,
  policies,
  agents,
  workspaceId,
  hasWorkspacePolicy,
}: PoliciesEditableViewProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [target, setTarget] = useState<PolicyEditorTarget | null>(null);

  const matrix = useMemo(
    () => policiesToMatrix(policies, agents),
    [policies, agents]
  );

  const policyById = useMemo(
    () => new Map(policies.map((p) => [p.id, p])),
    [policies]
  );

  const openCreate = () => {
    // No workspace policy yet → default new rules to workspace scope so the
    // header action lines up with the baseline strip's "Set workspace policy".
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

  const handleAddRule = (scope: AddRuleScope) => {
    setTarget(
      scope.subjectType === "workspace"
        ? { mode: "create-workspace" }
        : { mode: "create-agent", agentId: scope.subjectId }
    );
    setOpen(true);
  };

  const handleSetWorkspacePolicy = () => {
    setTarget({ mode: "create-workspace" });
    setOpen(true);
  };

  return (
    <>
      <div className="space-y-4">
        <BaselineStrip
          baseline={baseline}
          hasWorkspacePolicy={hasWorkspacePolicy}
          onSetWorkspacePolicy={handleSetWorkspacePolicy}
        />
        {matrix.subjects.length === 0 ? (
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
          <PoliciesMatrix
            matrix={matrix}
            agents={agents}
            onEditRule={handleEditRule}
            onAddRule={handleAddRule}
          />
        )}
      </div>
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
