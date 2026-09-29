"use server";

import type {
  PolicyRuleCreateRequest,
  PolicyRuleResponse,
  PolicyRuleUpdateRequest,
} from "@/api/client/types.gen";
import {
  zCreatePolicyRuleV1PoliciesPostBody,
  zCreatePolicyRuleV1PoliciesPostResponse,
  zUpdatePolicyRuleV1PoliciesRuleIdPatchBody,
  zUpdatePolicyRuleV1PoliciesRuleIdPatchResponse,
} from "@/api/client/zod.gen";
import { createPolicy, deletePolicy, updatePolicy } from "@/lib/api";

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .join(", ");
    }
  }
  return fallback;
}

export async function createPolicyRuleAction(
  input: PolicyRuleCreateRequest
): Promise<PolicyRuleResponse> {
  const body = zCreatePolicyRuleV1PoliciesPostBody.parse(input);
  const { data, error } = await createPolicy(body);

  if (error || !data) {
    throw new Error(errorMessage(error, "Save failed"));
  }

  return zCreatePolicyRuleV1PoliciesPostResponse.parse(data);
}

export async function updatePolicyRuleAction(
  id: string,
  input: PolicyRuleUpdateRequest
): Promise<PolicyRuleResponse> {
  const body = zUpdatePolicyRuleV1PoliciesRuleIdPatchBody.parse(input);
  const { data, error } = await updatePolicy(id, body);

  if (error || !data) {
    throw new Error(errorMessage(error, "Save failed"));
  }

  return zUpdatePolicyRuleV1PoliciesRuleIdPatchResponse.parse(data);
}

export async function deletePolicyRuleAction(id: string): Promise<void> {
  const { error } = await deletePolicy(id);

  if (error) {
    throw new Error(errorMessage(error, "Delete failed"));
  }
}
