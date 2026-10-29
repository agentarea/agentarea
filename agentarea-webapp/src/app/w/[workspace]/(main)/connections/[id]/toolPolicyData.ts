import { getTranslations } from "next-intl/server";
import { getMCPInstanceToolPolicies } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { getViewerCapabilities } from "@/lib/workspace-context";
import type { ToolPolicyState } from "../tool-policy";

export interface ToolPoliciesResult {
  /** `null` when they could not be read. */
  policies: Record<string, ToolPolicyState> | null;
  /** Policies are a workspace admin's to change; everyone else reads them. */
  canEdit: boolean;
  error: string | null;
}

/**
 * Each tool's workspace default and the engine's verdict on it, which other
 * rules may make stricter. Every member may read them.
 */
export async function loadToolPolicies(
  instanceId: string
): Promise<ToolPoliciesResult> {
  const [{ canAdminister }, t] = await Promise.all([
    getViewerCapabilities(),
    getTranslations("MCPServersPage.instanceDetail.errors"),
  ]);
  try {
    const result = await getMCPInstanceToolPolicies(instanceId);
    if (result.error || !result.data) {
      return {
        policies: null,
        canEdit: canAdminister,
        error: apiErrorMessage(result, t("toolPoliciesLoadFailed")),
      };
    }
    return {
      policies: Object.fromEntries(
        result.data.tools.map(({ name, ...state }) => [name, state])
      ),
      canEdit: canAdminister,
      error: null,
    };
  } catch (error) {
    return {
      policies: null,
      canEdit: canAdminister,
      error: `${t("toolPoliciesLoadFailed")}: ${formatApiError(error)}`,
    };
  }
}
