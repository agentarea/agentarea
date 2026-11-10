import "server-only";
import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type { PolicyRuleResponse } from "@/api/client/types.gen";
import { createPolicy, deletePolicy, listPolicies } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getWorkspaceContext } from "@/lib/workspace-context";
import { requestWorkspacePath } from "@/lib/workspace-request";
import {
  parseToolPolicyChange,
  planToolPolicyChange,
  type ToolPolicy,
} from "./tool-policy";

// Rule writes in flight at once, so a large group does not flood the API.
const POLICY_WRITE_BATCH = 8;
// Failed tools named in the error before the rest are counted.
const FAILED_NAMES_SHOWN = 3;

export type ToolPolicyWriteResult = { ok: true } | { ok: false; error: string };

/**
 * Set the workspace default for tools of one connection. For each tool the new
 * rule is written before the old one goes, so a failure midway leaves it at
 * least as restricted as before, never open.
 *
 * `targetOf` names a tool as the runtime checks it for this kind of connection;
 * `toolsPath` is the connection's Tools page, refreshed once the rules change.
 */
export async function writeToolPolicies({
  connectionId,
  toolNames,
  policy,
  targetOf,
  toolsPath,
}: {
  connectionId: string;
  toolNames: string[];
  policy: ToolPolicy;
  targetOf: (connectionId: string, toolName: string) => string;
  toolsPath: (connectionId: string) => string;
}): Promise<ToolPolicyWriteResult> {
  const t = await getTranslations("MCPServersPage.instanceDetail.tools.policy");
  const change = parseToolPolicyChange({
    instanceId: connectionId,
    toolNames,
    policy,
  });
  if (!change) return { ok: false, error: t("saveFailed") };
  const { active } = await getWorkspaceContext();
  if (!active) return { ok: false, error: t("saveFailed") };

  const listed = await listPolicies({
    subject_type: "workspace",
    subject_id: active.id,
  });
  if (listed.error || !listed.data) {
    return { ok: false, error: apiErrorMessage(listed, t("saveFailed")) };
  }
  const rules = listed.data as PolicyRuleResponse[];

  const apply = async (toolName: string): Promise<string | null> => {
    const target = targetOf(change.instanceId, toolName);
    const plan = planToolPolicyChange(rules, active.id, target, change.policy);
    if (plan.create) {
      const created = await createPolicy({
        subject_type: "workspace",
        subject_id: active.id,
        target,
        effect: plan.create,
      });
      if (created.error) return apiErrorMessage(created, t("saveFailed"));
    }
    for (const id of plan.remove) {
      const deleted = await deletePolicy(id);
      if (deleted.error) return apiErrorMessage(deleted, t("saveFailed"));
    }
    return null;
  };

  const failed: string[] = [];
  let error: string | null = null;
  for (let i = 0; i < change.toolNames.length; i += POLICY_WRITE_BATCH) {
    const batch = change.toolNames.slice(i, i + POLICY_WRITE_BATCH);
    const results = await Promise.all(batch.map(apply));
    results.forEach((result, index) => {
      if (result) {
        failed.push(batch[index]);
        error ??= result;
      }
    });
  }

  revalidatePath(await requestWorkspacePath(toolsPath(change.instanceId)));
  if (!failed.length) return { ok: true };
  const named = failed.slice(0, FAILED_NAMES_SHOWN).join(", ");
  const more = failed.length - FAILED_NAMES_SHOWN;
  return {
    ok: false,
    error: `${more > 0 ? t("failedMore", { names: named, count: more }) : named}: ${error}`,
  };
}
