"use server";

import { getTranslations } from "next-intl/server";
import { revalidatePath } from "next/cache";
import {
  deleteMCPServerInstance,
  getMCPServerInstance,
  updateMCPServerInstance,
  verifyMCPServerInstance,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";
import { egressExitUpdateSpec } from "../egress-exit";
import { toolPolicyTarget, type ToolPolicy } from "../tool-policy";
import {
  writeToolPolicies,
  type ToolPolicyWriteResult,
} from "../tool-policy-write";

export async function verifyInstance(instanceId: string) {
  return verifyMCPServerInstance(instanceId);
}

export async function deleteInstance(instanceId: string) {
  return deleteMCPServerInstance(instanceId);
}

/**
 * Bind the exit a container connection leaves through, or unbind with null.
 * The update replaces the whole spec, so it is built from the stored one.
 */
export async function bindEgressExitAction(
  instanceId: string,
  exitId: string | null
): Promise<{ ok: true } | { ok: false; error: string }> {
  const t = await getTranslations("EgressExits.section");
  const current = await getMCPServerInstance(instanceId);
  if (current.error || !current.data) {
    return { ok: false, error: apiErrorMessage(current, t("saveFailed")) };
  }
  const result = await updateMCPServerInstance(instanceId, {
    json_spec: egressExitUpdateSpec(current.data.json_spec ?? {}, exitId),
  });
  if (result.error) {
    return { ok: false, error: apiErrorMessage(result, t("saveFailed")) };
  }
  revalidatePath(await requestWorkspacePath(`/connections/${instanceId}`));
  return { ok: true };
}

/** Set the workspace default for tools of this connection. */
export async function setToolPoliciesAction(
  instanceId: string,
  toolNames: string[],
  policy: ToolPolicy
): Promise<ToolPolicyWriteResult> {
  return writeToolPolicies({
    connectionId: instanceId,
    toolNames,
    policy,
    targetOf: toolPolicyTarget,
    toolsPath: (id) => `/connections/${id}/tools`,
  });
}
