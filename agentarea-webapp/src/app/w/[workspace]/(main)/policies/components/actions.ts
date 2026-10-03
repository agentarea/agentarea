"use server";
import { getTranslations } from "next-intl/server";

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

type PolicyActionResult =
  | { ok: true; data: PolicyRuleResponse }
  | { ok: false; error: string };

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
): Promise<PolicyActionResult> {
  const body = zCreatePolicyRuleV1PoliciesPostBody.parse(input);
  const { data, error } = await createPolicy(body);

  if (error || !data) {
    const t = await getTranslations("PoliciesPage.editor");
    return { ok: false, error: errorMessage(error, t("actions.saveFailed")) };
  }

  return {
    ok: true,
    data: zCreatePolicyRuleV1PoliciesPostResponse.parse(data),
  };
}

export async function updatePolicyRuleAction(
  id: string,
  input: PolicyRuleUpdateRequest
): Promise<PolicyActionResult> {
  const body = zUpdatePolicyRuleV1PoliciesRuleIdPatchBody.parse(input);
  const { data, error } = await updatePolicy(id, body);

  if (error || !data) {
    const t = await getTranslations("PoliciesPage.editor");
    return { ok: false, error: errorMessage(error, t("actions.saveFailed")) };
  }

  return {
    ok: true,
    data: zUpdatePolicyRuleV1PoliciesRuleIdPatchResponse.parse(data),
  };
}

export async function deletePolicyRuleAction(id: string): Promise<void> {
  const { error } = await deletePolicy(id);

  if (error) {
    const t = await getTranslations("PoliciesPage.editor");
    throw new Error(errorMessage(error, t("actions.deleteFailed")));
  }
}
