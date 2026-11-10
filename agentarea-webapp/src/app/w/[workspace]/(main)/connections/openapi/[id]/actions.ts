"use server";

import { openapiToolPolicyTarget, type ToolPolicy } from "../../tool-policy";
import {
  writeToolPolicies,
  type ToolPolicyWriteResult,
} from "../../tool-policy-write";

/** Set the workspace default for operations of this API connection. */
export async function setOpenAPIToolPoliciesAction(
  connectionId: string,
  toolNames: string[],
  policy: ToolPolicy
): Promise<ToolPolicyWriteResult> {
  return writeToolPolicies({
    connectionId,
    toolNames,
    policy,
    targetOf: openapiToolPolicyTarget,
    toolsPath: (id) => `/connections/openapi/${id}/tools`,
  });
}
