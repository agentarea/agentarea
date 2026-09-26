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

export async function previewNetworkPolicyAction(
  agentId: string
): Promise<EffectivePolicy> {
  try {
    const body =
      zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostBody.parse({
        agent_id: agentId,
      });
    if (!body.agent_id) {
      throw new Error("Agent is required");
    }

    const { data, error } = await previewEffectivePolicy({
      agent_id: body.agent_id,
    });
    if (error || !data) {
      throw new Error("Policy preview is unavailable");
    }

    return zPreviewEffectivePolicyV1GovernanceEffectivePolicyPreviewPostResponse.parse(
      data
    ).effective_policy;
  } catch {
    throw new Error("Unable to load agent policy preview");
  }
}

export async function getNetworkPeopleAccessAction(): Promise<NetworkPeopleAccessResponse> {
  const { data, error } = await getNetworkPeopleAccess();
  if (error || !data) throw new Error("Unable to load workspace people access");
  return zGetNetworkPeopleAccessV1NetworkPeopleAccessGetResponse.parse(data);
}
