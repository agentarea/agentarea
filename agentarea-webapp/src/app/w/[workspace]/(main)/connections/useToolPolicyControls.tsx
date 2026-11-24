"use client";

import { useCallback, useOptimistic, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { formatApiError } from "@/lib/api-errors";
import { ToolPolicySelect } from "./components/ToolPolicySelect";
import type { ToolPolicyControls } from "./components/ToolsTable";
import {
  sharedToolPolicy,
  withDefault,
  type ToolPolicy,
  type ToolPolicyState,
} from "./tool-policy";
import type { ToolPolicyWriteResult } from "./tool-policy-write";
import type { ToolPoliciesResult } from "./toolPolicyData";

const ALLOWED: ToolPolicyState = {
  default: "allow",
  effective: "allow",
  reason: null,
};

/**
 * The per-tool policy select and its group select for a connection's Tools
 * table, shown before the server answers. `save` writes the rules for one kind
 * of connection; `policyOf` is what the engine decides, for the table filters.
 */
export function useToolPolicyControls(
  toolPolicies: ToolPoliciesResult,
  save: (
    toolNames: string[],
    policy: ToolPolicy
  ) => Promise<ToolPolicyWriteResult>
): {
  controls: ToolPolicyControls | null;
  policyOf: ((toolName: string) => ToolPolicy) | null;
  error: string | null;
} {
  const t = useTranslations("MCPServersPage.instanceDetail.tools.policy");
  const [error, setError] = useState<string | null>(null);
  const [policies, showPolicies] = useOptimistic(
    toolPolicies.policies ?? {},
    (current, change: { names: string[]; policy: ToolPolicy }) => ({
      ...current,
      ...Object.fromEntries(
        change.names.map((name) => [
          name,
          withDefault(current[name] ?? ALLOWED, change.policy),
        ])
      ),
    })
  );
  const [, startPolicyChange] = useTransition();
  const policyOf = useCallback(
    (toolName: string): ToolPolicy => policies[toolName]?.effective ?? "allow",
    [policies]
  );

  if (toolPolicies.policies === null) {
    return { controls: null, policyOf: null, error };
  }

  const stateOf = (toolName: string) => policies[toolName] ?? ALLOWED;
  const setPolicy = (names: string[], policy: ToolPolicy) =>
    startPolicyChange(async () => {
      showPolicies({ names, policy });
      setError(null);
      try {
        const result = await save(names, policy);
        if (!result.ok) setError(result.error);
      } catch (err) {
        console.error("Failed to set tool policies", err);
        setError(`${t("saveFailed")}: ${formatApiError(err)}`);
      }
    });

  return {
    controls: {
      cell: (toolName: string) => (
        <ToolPolicySelect
          label={t("label")}
          value={stateOf(toolName).default}
          effective={stateOf(toolName)}
          onChange={
            toolPolicies.canEdit
              ? (policy) => setPolicy([toolName], policy)
              : undefined
          }
        />
      ),
      group: toolPolicies.canEdit
        ? (toolNames: string[]) => (
            <ToolPolicySelect
              label={t("groupLabel")}
              prefix={t("allPrefix")}
              value={sharedToolPolicy(policies, toolNames)}
              onChange={(policy) => setPolicy(toolNames, policy)}
            />
          )
        : null,
    },
    policyOf,
    error,
  };
}
