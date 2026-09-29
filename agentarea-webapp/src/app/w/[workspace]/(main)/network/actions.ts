"use server";

import type {
  EffectivePolicy,
  NetworkPeopleAccessResponse,
} from "@/api/client/types.gen";
import {
  zGetNetworkPeopleAccessV1NetworkPeopleAccessGetResponse,
  zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostBody,
  zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponse,
} from "@/api/client/zod.gen";
import { getNetworkPeopleAccess, previewEffectivePolicy } from "@/lib/api";

export type NetworkActionResult<T> = {
  data?: T;
  error?: unknown;
  status?: number;
};

function invalid(issues: { path: PropertyKey[]; message: string }[]) {
  return {
    error: {
      detail: issues.map((issue) => ({
        msg: `${issue.path.map(String).join(".") || "response"}: ${issue.message}`,
      })),
    },
  };
}

export async function previewNetworkPolicyAction(
  agentId: string
): Promise<NetworkActionResult<EffectivePolicy>> {
  const body =
    zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostBody.safeParse(
      { agent_id: agentId }
    );
  if (!body.success) return invalid(body.error.issues);
  if (!body.data.agent_id) {
    return invalid([{ path: ["agent_id"], message: "Required" }]);
  }

  const result = await previewEffectivePolicy({
    agent_id: body.data.agent_id,
  });
  if (result.error || !result.data) {
    console.error("Policy preview failed", result.status, result.error);
    return { error: result.error, status: result.status };
  }
  const parsed =
    zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponse.safeParse(
      result.data
    );
  if (!parsed.success) return invalid(parsed.error.issues);
  return { data: parsed.data.effective_policy, status: result.status };
}

export async function getNetworkPeopleAccessAction(): Promise<
  NetworkActionResult<NetworkPeopleAccessResponse>
> {
  const result = await getNetworkPeopleAccess();
  if (result.error || !result.data) {
    console.error("People access failed", result.status, result.error);
    return { error: result.error, status: result.status };
  }
  const parsed =
    zGetNetworkPeopleAccessV1NetworkPeopleAccessGetResponse.safeParse(
      result.data
    );
  if (!parsed.success) return invalid(parsed.error.issues);
  return { data: parsed.data, status: result.status };
}
