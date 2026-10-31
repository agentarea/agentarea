"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import type { PolicyRuleResponse } from "@/api/client/types.gen";
import {
  createPolicy,
  deleteMCPServerInstance,
  deletePolicy,
  listPolicies,
  verifyMCPServerInstance,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { getWorkspaceContext } from "@/lib/workspace-context";
import { requestWorkspacePath } from "@/lib/workspace-request";
import {
  parseToolPolicyChange,
  planToolPolicyChange,
  toolPolicyTarget,
  type ToolPolicy,
} from "../tool-policy";

export async function verifyInstance(instanceId: string) {
  return verifyMCPServerInstance(instanceId);
}

export async function deleteInstance(instanceId: string) {
  return deleteMCPServerInstance(instanceId);
}

// Rule writes in flight at once, so a large group does not flood the API.
const POLICY_WRITE_BATCH = 8;
// Failed tools named in the error before the rest are counted.
const FAILED_NAMES_SHOWN = 3;

/**
 * Set the workspace default for tools of this connection. For each tool the
 * new rule is written before the old one goes, so a failure midway leaves it
 * at least as restricted as before, never open.
 */
export async function setToolPoliciesAction(
  instanceId: string,
  toolNames: string[],
  policy: ToolPolicy
): Promise<{ ok: true } | { ok: false; error: string }> {
  const t = await getTranslations("MCPServersPage.instanceDetail.tools.policy");
  const change = parseToolPolicyChange({ instanceId, toolNames, policy });
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
    const target = toolPolicyTarget(change.instanceId, toolName);
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

  revalidatePath(
    await requestWorkspacePath(`/connections/${change.instanceId}/tools`)
  );
  if (!failed.length) return { ok: true };
  const named = failed.slice(0, FAILED_NAMES_SHOWN).join(", ");
  const more = failed.length - FAILED_NAMES_SHOWN;
  return {
    ok: false,
    error: `${more > 0 ? t("failedMore", { names: named, count: more }) : named}: ${error}`,
  };
}
